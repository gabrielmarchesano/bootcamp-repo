# Design — Etapa 1: Titular v7

> **Revisão 3** — este documento responde a dois ciclos de review. A Revisão 2 fechou
> o primeiro `design-review.json` (2 HIGH + 6 MEDIUM + 3 NIT). Esta Revisão 3 fecha o
> segundo review (`design-review.json`/`design-review.md`, veredito CHANGES_REQUESTED,
> 4 MEDIUM + 2 NIT), cujos achados eram lacunas de especificação locais: a assinatura
> concreta de `_initial_account_status`, a fonte de KYC na abertura de conta adicional,
> a borda "zero contas" do QIT001051, e o nome não-verificado da UNIQUE de documento no
> caminho 409. As mudanças estão resolvidas no corpo abaixo e resumidas na seção
> **"Respostas à revisão"** no fim. As premissas verificadas pelos reviews (schema,
> códigos de erro livres, escopo de propagação de N contas, seeds de `fee`) foram
> reconfirmadas contra o código real e estão incorporadas como fatos.

## Overview

Esta etapa migra o modelo central de titular (`customer`) do vocabulário v6 (`cpf`, `type` em `INDIVIDUAL`/`MEI`, `cnpj`) para o v7 (`person_type` em `NATURAL`/`LEGAL`, `document` único, `legal_nature` em `EI`/`SLU`/`LTDA`, `owner_customer_id`, mais três colunas GERADAS pelo banco: `exposure_customer_id`, `fee_segment`, `microcredit_eligible`). A mudança atravessa todas as camadas da aplicação FastAPI (`src/models` → `src/repositories` → `src/controllers` → `src/resources` + `src/schemas`/`src/dtos`), introduz a tabela de vínculos PJ→PF (`customer_relationship`), muda a cardinalidade titular↔conta de 1:1 para 1:N, troca a chave de tarifação de `customer.type` para `customer.fee_segment`/`fee.customer_segment`, e entrega um script de migração v6→v7 idempotente que desdobra cada MEI em dois titulares.

O escopo é **somente o titular v7**. Nada de microcrédito, jobs ou fatura (Etapa 2/3) — o schema v7 já tem essas tabelas e aqui só garantimos que ele sobe e que o titular funciona de ponta a ponta (Fluxo 1 da RFC: PF, EI/MEI, SLU, LTDA).

**Stack travada** (não muda após aprovação): Python 3 + FastAPI; SQLAlchemy ORM (declarativo, `models/base.py`); PostgreSQL 15 (`gen_random_uuid`, colunas `GENERATED ALWAYS AS ... STORED`); validação de entrada por JSON Schema (`jsonschema` draft-07 + `src/utils/schema_handler.py`), **não** Pydantic; psycopg2 como driver; testes em pytest de integração contra um Postgres real (`tests/utils/db_utils.py` recria o schema a cada reset). Imports usam `src` como raiz (`from models.customer import Customer`), nunca `from src...`. O schema v7 **não pode conter o caractere de porcentagem** (o `db_utils.py` roda o arquivo via psycopg2, que trata `%` como marcador de parâmetro — vale também para o script de migração 1.9).

O schema v7 em `database/database.sql` é a fonte da verdade e **já está escrito** — esta etapa adapta o código Python a ele; não reescrevemos o schema, com **duas exceções pontuais e justificadas**: (1) o script de migração (item 1.9, numa pasta nova); (2) **nomear explicitamente a UNIQUE de `document`** (`CONSTRAINT ux_customer_document UNIQUE (document)`) para que o caminho de erro 409 de documento duplicado não dependa de um nome auto-gerado adivinhado (finding 4 / §1.5). A exceção (2) não muda a semântica do schema (a UNIQUE já existe), só torna o nome determinístico.

---

## Fatos do schema v7 que o design herda (não decidir, obedecer)

Tabela `customer` (DDL já no schema, transcrito do arquivo real):

- Colunas de entrada: `id` (UUID PK, default `gen_random_uuid()`), `person_type` (`CHECK IN ('NATURAL','LEGAL')`), `document` (`VARCHAR(14) NOT NULL UNIQUE`, só dígitos — 11 p/ CPF, 14 p/ CNPJ), `name` (TEXT), `birth_date` (DATE, nullable — só NATURAL), `legal_nature` (`CHECK IN ('EI','SLU','LTDA')`, nullable — só LEGAL), `owner_customer_id` (UUID, nullable — só EI), `owner_person_type` (`CHECK (= 'NATURAL')`, nullable — alvo da FK composta), `annual_revenue` (BIGINT `CHECK >= 0`), `revenue_reference_date` (DATE default `CURRENT_DATE`), `kyc_status_id`, `is_pep` (BOOLEAN NOT NULL default FALSE), `created_at`, `updated_at`.
- **Colunas GERADAS (`GENERATED ALWAYS AS ... STORED`) — o banco calcula, o código NUNCA grava** (expressões exatas, verbatim do schema):
  - `exposure_customer_id = COALESCE(owner_customer_id, id)` — raiz do patrimônio.
  - `fee_segment = CASE WHEN person_type = 'NATURAL' OR legal_nature = 'EI' THEN 'INDIVIDUAL' ELSE 'BUSINESS' END` — segmento de tarifa.
  - `microcredit_eligible = (annual_revenue <= 36000000)` — elegibilidade (R$ 360.000,00 em centavos).
- CHECKs relevantes (verbatim do schema):
  - `ck_document`: `(person_type='NATURAL' AND document ~ '^[0-9]{11}$') OR (person_type='LEGAL' AND document ~ '^[0-9]{14}$')`.
  - `ck_fields_by_person_type`: `(person_type='NATURAL') = (birth_date IS NOT NULL) AND (person_type='LEGAL') = (legal_nature IS NOT NULL)`.
  - `ck_pep_natural`: `NOT is_pep OR person_type = 'NATURAL'` — ou seja, `is_pep=true` **só** é aceito em NATURAL; `is_pep=false` é aceito em ambos.
  - `ck_ei_owner`: `(legal_nature IS NOT DISTINCT FROM 'EI') = (owner_customer_id IS NOT NULL) AND (owner_customer_id IS NULL) = (owner_person_type IS NULL)`.
  - FK composta `fk_ei_owner (owner_customer_id, owner_person_type) → customer(id, person_type)` — **o dono do EI é obrigatoriamente NATURAL por integridade do banco**.
- UNIQUEs alvo de FK composta: `ux_customer_person_type (id, person_type)`, `ux_customer_exposure (id, exposure_customer_id)`. Índice parcial `ix_customer_owner (owner_customer_id) WHERE owner_customer_id IS NOT NULL`.
- **UNIQUE de `document`:** no schema está **inline sem nome** (`document VARCHAR(14) NOT NULL UNIQUE`), que o Postgres auto-nomeia `customer_document_key`. Como o caminho 409 de documento duplicado depende de casar esse nome em Python, **esta etapa nomeia a constraint explicitamente** (`CONSTRAINT ux_customer_document UNIQUE (document)`) — ver 1.5 / finding 4. É a única alteração de DDL permitida fora da migração nesta etapa, e torna o mapa `UNIQUE_DOCUMENT_CONSTRAINTS` determinístico.

Tabela `customer_relationship` (DDL já no schema, verbatim):

```
legal_customer_id    UUID NOT NULL
legal_person_type    TEXT NOT NULL DEFAULT 'LEGAL'   CHECK (legal_person_type = 'LEGAL')
natural_customer_id  UUID NOT NULL
natural_person_type  TEXT NOT NULL DEFAULT 'NATURAL' CHECK (natural_person_type = 'NATURAL')
role                 TEXT NOT NULL CHECK (role IN ('PARTNER','ADMINISTRATOR','ATTORNEY'))
created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
PRIMARY KEY (legal_customer_id, natural_customer_id, role)
FK fk_relationship_legal   (legal_customer_id, legal_person_type)     → customer(id, person_type)
FK fk_relationship_natural (natural_customer_id, natural_person_type) → customer(id, person_type)
INDEX ix_customer_relationship_natural (natural_customer_id)
```

Chave primária composta de três colunas: a mesma PF pode ser PARTNER e ADMINISTRATOR da mesma PJ (duas linhas), mas não duas vezes PARTNER. Não há coluna `id` própria. As FKs compostas garantem, pelo banco, que o lado "legal" é LEGAL e o lado "natural" é NATURAL.

Tabela `account` (DDL já no schema v7): `customer_id UUID REFERENCES customer(id)` **não é mais UNIQUE** no v7 (há `ix_account_customer (customer_id) WHERE customer_id IS NOT NULL` e `ux_account_customer UNIQUE (id, customer_id)` que é alvo de FK composta do loan, mas **não** restringe a 1 conta por cliente). Comentário do schema: "N contas por titular". **O modelo SQLAlchemy v6 ainda declara `customer_id ... unique=True` e `account` como `uselist=False` — os dois precisam mudar.**

Tabela `fee` (DDL já no schema v7): PK `(method, customer_segment, effective_from)`, coluna `customer_segment` com `CHECK IN ('INDIVIDUAL','BUSINESS')`. **Seeds v7 confirmados** (lidos no arquivo real): `('TEF','INDIVIDUAL',100), ('TEF','BUSINESS',100), ('PIX','INDIVIDUAL',0), ('PIX','BUSINESS',0), ('TED','INDIVIDUAL',1000), ('TED','BUSINESS',1000)`. **O modelo SQLAlchemy ainda tem `customer_type` — precisa virar `customer_segment`.**

---

## 1.2 — `src/models/customer.py`

Reescrever o modelo para espelhar a tabela v7. Decisões concretas:

- **Remover** os atributos de classe `INDIVIDUAL = "INDIVIDUAL"` e `MEI = "MEI"` (não existem mais no v7). Adicionar constantes de vocabulário novo como atributos de classe, no mesmo estilo (`NATURAL = "NATURAL"`, `LEGAL = "LEGAL"`, `EI = "EI"`, `SLU = "SLU"`, `LTDA = "LTDA"`), porque outras camadas comparam contra elas (igual a `Account.CUSTOMER`).
- Trocar colunas: remover `cpf`, `type`, `cnpj`, **e `microcredit_eligible` como coluna gravável** (o v6 a declarava `nullable=False` e gravável — vira coluna GERADA, ver abaixo). Adicionar:
  - `person_type = Column(String, nullable=False)`
  - `document = Column(String, nullable=False, unique=True)` (`String`; o schema usa `VARCHAR(14)` com regex — manter `String` como o resto do projeto, sem `CHAR`)
  - `legal_nature = Column(String)` (nullable)
  - `owner_customer_id = Column(UUID(as_uuid=True), ForeignKey("customer.id"))` (nullable)
  - `owner_person_type = Column(String)` (nullable)
  - `birth_date = Column(Date, nullable=True)` (deixa de ser `nullable=False`; só NATURAL)
- **Colunas geradas mapeadas como somente-leitura.** `exposure_customer_id`, `fee_segment`, `microcredit_eligible` precisam ser lidas pelo ORM mas **nunca escritas** (o banco recusa INSERT/UPDATE que as cite). **Escolha: `FetchedValue()`** — `Column("exposure_customer_id", UUID(as_uuid=True), server_default=FetchedValue())`, `Column("fee_segment", String, server_default=FetchedValue())`, `Column("microcredit_eligible", Boolean, server_default=FetchedValue())`. Motivo sobre `Computed`: `Computed` faz o SQLAlchemy querer emitir o DDL `GENERATED ALWAYS AS` em `create_all`, mas o projeto **não** cria tabelas pelo ORM (o schema vem do `database.sql`); `FetchedValue` apenas informa "o banco preenche, não gere na cláusula INSERT e releia depois", que é exatamente o contrato. Essas três colunas **não entram** em `CustomerRepository.create`/`update_revenue`. **Consequência (ver 1.5):** `FetchedValue` **não** repopula o atributo automaticamente após um INSERT sem `RETURNING` — é preciso `session.refresh(...)` explícito depois do flush para lê-las.
- Relationships: manter `kyc_status`. **Trocar o relationship de conta:**
  ```python
  accounts = relationship(
      "Account",
      back_populates="customer",
      uselist=True,
      order_by="Account.created_at",   # ordem determinística: a mais antiga é accounts[0]
      lazy="selectin",
  )
  ```
  **Renomear o atributo para `accounts`** (plural) para refletir N contas e impedir que código antigo que fazia `customer.account` continue "funcionando por acaso". `order_by="Account.created_at"` é **obrigatório** (finding 5): sem ele, `uselist=True`+`selectin` não garante ordem, e tanto o GET quanto o DTO de criação assumem "a mais antiga = `accounts[0]`". No lado `Account`, trocar `customer_id = Column(..., unique=True)` por **sem `unique`** e manter `customer = relationship("Account"-inverse..., back_populates="accounts")` (N:1, escalar, inalterado em cardinalidade).
- `owner` self-referential (`remote_side=[id]`) é **opcional e fica de fora** desta etapa (ninguém navega PF←EI pelo ORM; a FK basta).

**Propagação de N contas (onde o código assumia conta única):**

1. `CustomerDTO` (`obj_to_dict`, `creation_to_dict`) lê `customer.account` — ver 1.5. **Único ponto que lê o lado 1:N.**
2. `AccountDTO.obj_to_dict` lê `account.customer.microcredit_eligible` (lado N:1 account→customer, **não muda**).
3. `PixKeyController._own_key_data` e `_key_value` leem `account.customer` (lado N:1, **não muda**) — ver 1.7.
4. `TransferController._pix_manual_fields`/tarifas leem `source.customer`/`destination.customer` (lado N:1, **não muda**) — ver 1.8.

O lado "uma conta tem um titular" (`Account.customer`, N:1) **não muda**; só o inverso (`Customer.accounts`, 1:N) muda. (A revisão confirmou por grep que o **único** uso de `customer.account` singular está no `customer_dto.py`.)

---

## 1.3 — `src/models/customer_relationship.py` (novo)

Criar o modelo espelhando a tabela `customer_relationship`. Como a PK é composta e **não há coluna `id`**, declarar `primary_key=True` nas três colunas da PK:

```python
from sqlalchemy import Column, DateTime, ForeignKeyConstraint, String, func
from sqlalchemy.dialects.postgresql import UUID
from models.base import Base


class CustomerRelationship(Base):
    __tablename__ = "customer_relationship"

    PARTNER = "PARTNER"
    ADMINISTRATOR = "ADMINISTRATOR"
    ATTORNEY = "ATTORNEY"

    legal_customer_id   = Column(UUID(as_uuid=True), primary_key=True)
    legal_person_type   = Column(String, nullable=False, server_default="LEGAL")
    natural_customer_id = Column(UUID(as_uuid=True), primary_key=True)
    natural_person_type = Column(String, nullable=False, server_default="NATURAL")
    role                = Column(String, primary_key=True)
    created_at          = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["legal_customer_id", "legal_person_type"],
            ["customer.id", "customer.person_type"],
            name="fk_relationship_legal",
        ),
        ForeignKeyConstraint(
            ["natural_customer_id", "natural_person_type"],
            ["customer.id", "customer.person_type"],
            name="fk_relationship_natural",
        ),
    )
```

Decisões:
- **Declarar as duas `ForeignKeyConstraint` compostas em `__table_args__`** (fidelidade ao schema; sem custo). **Não** declarar relationships ORM para `customer` (não há navegação necessária nesta etapa; um self-join duplo adicionaria ambiguidade). O repositório insere por id.
- `legal_person_type`/`natural_person_type` ganham `server_default` igual ao DEFAULT da coluna; o repositório **não** seta (deixa o default do banco; menos acoplamento).
- Registrar em `src/models/__init__.py`: adicionar `from models.customer_relationship import CustomerRelationship` logo após `from models.customer import Customer`.

---

## 1.4 — JSON Schemas por `person_type`

Reescrever `src/schemas/post_customer.json` e `src/schemas/patch_customer.json` seguindo o estilo existente (`title`, `type: object`, `properties`, `required`, `additionalProperties: false`, blocos condicionais). O JSON Schema é a **primeira** barreira; o `SchemaHandler.validate` roda no resource, **antes** do controller — então "tipo trocado → 400 antes de qualquer consulta ao banco" é garantido pelo pipeline, não por lógica extra.

**`post_customer.json`** — propriedades: `person_type` (`enum: ["NATURAL","LEGAL"]`), `document` (`string`, `pattern: "^\\d{11}$|^\\d{14}$"`), `name` (string 1–255), `birth_date` (`string`, pattern data), `legal_nature` (`enum: ["EI","SLU","LTDA"]`), `owner_customer_id` (`string` UUID), `annual_revenue` (integer, `minimum: 0`, `maximum: 100000000000`), `is_pep` (boolean). `required`: `["person_type", "document", "name", "annual_revenue"]`. `additionalProperties: false`.

> **`annual_revenue` máximo = 1e11 é um teto de sanidade da APLICAÇÃO, não derivado do schema.** (finding 2a) O DDL v7 só tem `CHECK (annual_revenue >= 0)` — não há teto no banco. O cap 1e11 (mesmo valor que o v6 usava) existe só para barrar lixo numérico; o implementador **não** deve procurar um CHECK de limite superior no DDL (não existe).

Regras condicionais via `allOf` com blocos `if/then` (draft-07, igual ao estilo v6 que proíbe `cnpj` em INDIVIDUAL). O ramo "proibido" se expressa com `"not": {"required": [...]}`:

```json
"allOf": [
  { "if": {"properties":{"person_type":{"const":"NATURAL"}},"required":["person_type"]},
    "then": {"required":["birth_date"],
             "properties":{"document":{"pattern":"^\\d{11}$"}},
             "not":{"anyOf":[{"required":["legal_nature"]},{"required":["owner_customer_id"]}]}} },
  { "if": {"properties":{"person_type":{"const":"LEGAL"}},"required":["person_type"]},
    "then": {"required":["legal_nature"],
             "properties":{"document":{"pattern":"^\\d{14}$"}},
             "not":{"anyOf":[{"required":["birth_date"]},{"required":["is_pep"]}]}} },
  { "if": {"properties":{"legal_nature":{"const":"EI"}},"required":["legal_nature"]},
    "then": {"required":["owner_customer_id"]} },
  { "if": {"anyOf":[{"properties":{"legal_nature":{"const":"SLU"}},"required":["legal_nature"]},
                    {"properties":{"legal_nature":{"const":"LTDA"}},"required":["legal_nature"]}]},
    "then": {"not":{"required":["owner_customer_id"]}} }
]
```

**Correções da revisão aplicadas ao snippet:**
- **(finding 1)** Removido o campo-fantasma `is_pep_na` (não existe em lugar nenhum; `additionalProperties:false` já cobre campos desconhecidos). O `not` do ramo NATURAL proíbe **exatamente** `legal_nature` e `owner_customer_id`.
- **(finding 1) `is_pep` em LEGAL:** o DDL `ck_pep_natural` aceita `is_pep=false` em LEGAL mas recusa `is_pep=true`. Para nunca deixar um `true` virar `IntegrityError` (500) no banco, **o ramo LEGAL proíbe `is_pep` por completo** (`"not":{"anyOf":[...,{"required":["is_pep"]}]}`). Decisão fixada: `is_pep` é um campo **exclusivo de NATURAL**; enviá-lo em LEGAL (true **ou** false) → **400**. (Simples e sem ambiguidade; a semântica "PJ herda PEP dos sócios" do comentário do schema não é modelada nesta etapa.)

**(finding 2b) Tabela de contrato — 8 payloads representativos e resultado exato.** O implementador escreve e testa contra isto (não re-deriva a interação de ramos draft-07):

| # | Payload (campos relevantes) | Resultado | Cláusula que decide |
|---|---|---|---|
| 1 | `person_type=NATURAL, document=<11 dígitos>, birth_date, annual_revenue` | **passa** schema | ramo NATURAL ok |
| 2 | `person_type=NATURAL, legal_nature=EI, ...` | **400** | ramo NATURAL `not.required[legal_nature]` |
| 3 | `person_type=NATURAL, owner_customer_id=<uuid>, ...` | **400** | ramo NATURAL `not.required[owner_customer_id]` |
| 4 | `person_type=NATURAL, document=<14 dígitos>, ...` | **400** | ramo NATURAL `document.pattern ^\d{11}$` |
| 5 | `person_type=LEGAL, legal_nature=EI, owner_customer_id, document=<14>, annual_revenue` | **passa** schema | ramos LEGAL + EI ok |
| 6 | `person_type=LEGAL` **sem** `legal_nature` | **400** | ramo LEGAL `required[legal_nature]` |
| 7 | `person_type=LEGAL, legal_nature=EI` **sem** `owner_customer_id` | **400** | bloco EI `required[owner_customer_id]` |
| 8 | `person_type=LEGAL, legal_nature=SLU, owner_customer_id=<uuid>` | **400** | bloco SLU/LTDA `not.required[owner_customer_id]` |

Casos extras pinados (mesmas regras, para o conjunto de testes): `LEGAL + birth_date` → 400 (ramo LEGAL `not.required[birth_date]`); `LEGAL + document=<11 dígitos>` → 400 (`document.pattern ^\d{14}$`); `LEGAL + is_pep` → 400 (ramo LEGAL `not.required[is_pep]`). Nota: um `LEGAL` sem `legal_nature` já cai em 400 pelo caso 6, então o bloco SLU/LTDA só precisa cobrir o caso 8 (SLU/LTDA presente **com** `owner_customer_id`).

**`patch_customer.json`** — PATCH é atualização de faturamento (`update_revenue`). **Manter apenas `annual_revenue`** (`required: ["annual_revenue"]`, `properties.annual_revenue` integer `minimum:0`/`maximum:100000000000`, `additionalProperties: false`), igual ao v6. **Não** permitir trocar `person_type`/`document`/`legal_nature` por PATCH (ver D-PATCH).

---

## 1.5 — Controller / Repository / DTO do titular

### `src/repositories/customer_repository.py`

- `create(customer_data, birth_date, kyc_status)`: **perde o parâmetro `microcredit_eligible`** (não é mais calculado no app). Parar de gravar `cpf`/`type`/`cnpj`/`microcredit_eligible`. Gravar `person_type`, `document`, `name`, `birth_date` (só NATURAL — `None` p/ LEGAL), `legal_nature` (só LEGAL), `owner_customer_id` (só EI), `owner_person_type` (ver abaixo), `annual_revenue`, `is_pep`. **Nunca** setar `exposure_customer_id`, `fee_segment`, `microcredit_eligible` (gerados).
  - `owner_person_type`: a FK composta `fk_ei_owner` exige `owner_person_type='NATURAL'` quando há `owner_customer_id`, e a coluna **não tem DEFAULT**. Decisão: o repositório **seta `owner_person_type = Customer.NATURAL` sempre que `owner_customer_id` for informado** (e deixa `None` caso contrário, respeitando `ck_ei_owner`).
- Trocar lookups: remover `get_by_cpf`/`get_by_cnpj`; adicionar `get_by_document(document)` filtrando `Customer.document == document`. `get_by_id` permanece.
- `update_revenue(customer, annual_revenue)`: **perde o parâmetro `microcredit_eligible`**; grava só `annual_revenue`, `revenue_reference_date`, `updated_at`. **(finding 6)** Como a elegibilidade passa a ser lida do banco (coluna gerada) e o código atual não dá `flush` antes do `commit`, o controller **adiciona um `flush` + `refresh`** após `update_revenue` (ver controller abaixo).

### `src/controllers/customer_controller.py`

**Elegibilidade e colunas geradas (findings 6/11 do 1º review; finding 6 do 2º review):** **não calcular mais `microcredit_eligible` no controller**. **Decisão fixada:** **remover a constante `MICROCREDIT_REVENUE_CAP` do `customer_controller.py` e as duas computações `annual_revenue <= MICROCREDIT_REVENUE_CAP`** (uma no `create`, uma no `update_revenue`). A elegibilidade passa a ser **somente-leitura** da coluna gerada `customer.microcredit_eligible` (o banco é a única fonte da verdade; manter uma constante `36_000_000` no Python convida religar lógica a ela — exatamente a deriva que o comentário do schema alerta). Se uma etapa futura precisar do número para uma mensagem, que ela introduza um valor **display-only** próprio; esta etapa não deixa a constante residual. O valor gerado é lido via `session.refresh`. **Sequência exata (ordem é load-bearing — não introduzir flush/refresh antes do try):**

```
1. valida DV, EI-owner, duplicidade (get_by_document), KYC, idade/PEP (só NATURAL)
2. customer = repo.create(...)                      # add, SEM flush
3. account  = account_repo.create_for_customer(...) # usa no_autoflush de propósito
4. try:
       session.flush()                              # único flush; INSERT customer+account
   except IntegrityError:
       session.rollback(); traduz UNIQUE de documento -> 409 ; re-raise senão
5. session.refresh(customer, ["exposure_customer_id", "fee_segment", "microcredit_eligible"])
6. outbox.add(ACCOUNT_OPENED, ...)
7. session.commit()
8. return CustomerDTO.creation_to_dict(customer, account)   # account fresco, ver DTO
```

- O `refresh` (passo 5) vem **depois** do `try/except` bem-sucedido, nunca antes — senão a corrida de documento duplicado vira 500 em vez de 409 (o `create_for_customer` usa `no_autoflush` justamente para manter o INSERT do customer dentro do `try`). `session.refresh` com lista de atributos re-SELECTa só essas colunas; as três estão mapeadas (1.2), então não levanta por nome inexistente.
- `creation_to_dict` lê `microcredit_eligible` **depois** do refresh (passo 8), nunca stale/None (finding 11).
- `update_revenue` espelha a sequência: `repo.update_revenue(...)` → `session.flush()` → `session.refresh(customer, ["microcredit_eligible", "fee_segment", "exposure_customer_id"])` → `session.commit()` → `CustomerDTO.obj_to_dict(customer)`.

**Validação de dígito verificador por `person_type`:**
- NATURAL → `is_valid_cpf(document)`; falha → `InvalidDocumentNumber(document)` (QIT001003, 422).
- LEGAL → `is_valid_cnpj(document)`; falha → `InvalidCnpj(document)` (QIT001011, 422).
(Ambas já existem em `utils/document_number.py`; não mudam.)

**Dono do EI tem de ser pessoa natural → novo erro QIT001050 (`EiOwnerNotNatural`):** quando `legal_nature == "EI"`, o controller resolve `owner_customer_id` via `customer_repository.get_by_id`:
- `owner_customer_id` não existe → **QIT001050** (a RFC define QIT001050 como "dono do EI não é pessoa natural"; cobre o dono inexistente, `description` indicando ausência). Ver D-EI-OWNER.
- dono existe mas `person_type != "NATURAL"` → **QIT001050**.
- A FK composta `fk_ei_owner` recusaria no flush de qualquer forma; a checagem no controller existe para dar **422 QIT001050** amigável em vez de deixar vazar `IntegrityError` (500).

**Fluxo de criação (ordem adaptada do v6):**
1. Validar DV conforme `person_type`.
2. Se EI, validar que `owner_customer_id` existe e é NATURAL (QIT001050).
3. `get_by_document` → se já existe, **QIT001010 `CustomerAlreadyExists`** (campo `"document"`).
4. KYC/PLD (`check_kyc`) — hoje recebe o CPF; passa a receber `document`. Para LEGAL o mock sempre aprova (ver D-KYC-PJ / finding 9).
5. Idade / `is_pep` **só para NATURAL**. Para LEGAL não há `birth_date` nem idade; `_initial_account_status` passa a receber `person_type` e **pula** idade/PEP quando LEGAL (nasce ACTIVE, salvo KYC REJECTED). **Assinatura nova fixada (finding 1):**

```python
def _initial_account_status(self, person_type: str, kyc_status: str, age: int = None, is_pep: bool = False):
    """Status de nascimento da conta + motivo. LEGAL não tem idade nem PEP:
    curto-circuita ANTES de qualquer comparação de idade (age pode ser None)."""
    if kyc_status == KycStatus.REJECTED:
        return AccountStatus.REJECTED, "KYC_REJECTED"
    if person_type == Customer.LEGAL:
        return AccountStatus.ACTIVE, None          # sem gate de idade/PEP p/ LEGAL
    if age < MINIMUM_AGE:                           # daqui p/ baixo só NATURAL (age != None)
        return AccountStatus.REJECTED, "UNDERAGE"
    if is_pep:
        return AccountStatus.PENDING, "PEP_REVIEW"
    if age >= REVIEW_AGE:
        return AccountStatus.PENDING, "SENIOR_REVIEW"
    return AccountStatus.ACTIVE, None
```

O curto-circuito `person_type == LEGAL` vem **depois** do KYC (uma PJ também pode nascer REJECTED se o KYC recusar) e **antes** de qualquer `age <`, de modo que `age=None` em LEGAL **nunca** é comparado. Para NATURAL o controller passa `age=self._age_in_years(birth_date)` e `is_pep=customer_data.get("is_pep", False)`; para LEGAL passa `age=None, is_pep=False` (defaults — pode omitir). As duas únicas chamadas (`create` e `open_account`) usam esta mesma assinatura.
6. Criar customer + abrir **a primeira conta** (uma conta no cadastro, como v6).
7. `flush` com o mesmo `try/except IntegrityError` do v6 para a corrida de documento duplicado. Adaptar `UNIQUE_DOCUMENT_CONSTRAINTS` para a nova constraint: o UNIQUE agora é em `document`. O mecanismo de leitura do nome já existe (`_violated_document` lê `error.orig.diag.constraint_name`); o mapa vira `{"<nome da UNIQUE de document>": "document"}` e o `except` levanta `CustomerAlreadyExists("document", document)`.

   **(finding 4 — o caminho 409 não pode depender de um nome adivinhado.)** O UNIQUE de `document` está declarado **inline sem nome** no `database.sql`, então o Postgres o auto-nomeia (`customer_document_key`, padrão `<tabela>_<coluna>_key`). Um nome errado faz `_violated_document` devolver `None`, o `except` re-levanta e a **corrida de documento duplicado vira 500 em vez de 409, silenciosamente**. Esta etapa **fecha** isso com duas ações obrigatórias, não com um "confirmar depois":
   - **(a) Nomear a UNIQUE explicitamente no `database.sql`.** Trocar o inline `document VARCHAR(14) NOT NULL UNIQUE` por `document VARCHAR(14) NOT NULL` + `CONSTRAINT ux_customer_document UNIQUE (document)`. **Esta é a única alteração de DDL permitida fora da migração nesta etapa**, e é justificada: o schema v7 nomeia todas as outras constraints relevantes (`ck_document`, `fk_ei_owner`, `ux_customer_person_type`...), então deixar a de `document` anônima é inconsistência, e o contrato de erro 409 depende do nome ser determinístico. O mapa Python fica `{"ux_customer_document": "document"}`, sem adivinhação. Checar antes que `ux_customer_document` não colide com nome já usado no arquivo.
   - **(b) Teste de integração que trava o contrato.** Um teste que insere dois `customer` com o mesmo `document` concorrendo com a pré-checagem (ou força o 2º INSERT direto, driblando o `get_by_document`) e **asserta 409 QIT001010, não 500**. Este teste é o guarda que pega qualquer regressão de nome/caminho e é **obrigatório** nesta etapa (não é o teste de migração 4.7, que é opcional).

   Se, por qualquer razão, (a) não puder entrar (ex.: congelamento duro do `database.sql`), então (b) + confirmar o auto-nome real com `\d customer` no banco carregado pelo `db_utils.py` é o **mínimo** — mas (a) é a opção escolhida por tornar o Python determinístico.

### `src/dtos/customer_dto.py`

**(finding 4 — contrato do GET fixado, sem hedge.)** O GET `/customers/{id}` muda de corpo por causa de N contas. **Decisão travada:** manter `account_id` escalar **E** adicionar a lista `accounts` — para minimizar quebra dos testes do Fluxo 1 que leem `customer["account_id"]`.

- `obj_to_dict(customer)`:
  - trocar `cpf`/`type`/`cnpj` por `person_type`, `document`, `legal_nature` (str|None), `owner_customer_id` (str|None);
  - adicionar `exposure_customer_id` (str) e `fee_segment` (str) — gerados, úteis para integradores e testes;
  - `microcredit_eligible` continua;
  - `birth_date` → `customer.birth_date.isoformat() if customer.birth_date else None` (nullable em LEGAL);
  - **`account_id`** = conta mais antiga: `str(customer.accounts[0].id) if customer.accounts else None` (determinístico pelo `order_by="Account.created_at"` do relationship, finding 5);
  - **`accounts`** = lista de `{account_id, branch, account_number, status, status_reason}`, iterando `customer.accounts` (já ordenada). **(finding 5 — projeção fina deliberada, documentada.)** Esta lista embutida é **de propósito** mais magra que `AccountDTO.obj_to_dict` (que o endpoint dedicado `GET /customers/{id}/accounts` usa, trazendo também `balance`/`held_balance`/`available_balance`/`type`/`customer_id`/`microcredit_eligible`/`created_at`). Motivo: `GET /customers/{id}` é a **visão do titular** — identifica as contas e seus status sem carregar saldos (que mudam a cada transação e cujo lar é o endpoint de conta); `GET /customers/{id}/accounts` é a **visão de contas**, completa. Duas formas, dois contratos propositais; o integrador usa o endpoint de contas quando precisa de saldo. (Alternativa — reusar `AccountDTO.obj_to_dict` embutido — foi considerada e **rejeitada**: embutiria saldo numa resposta de titular, acoplando dois agregados e inflando o payload do Fluxo 1.)
- `creation_to_dict(customer, account)`: **(finding 5)** passa a receber o objeto `account` recém-criado como parâmetro (threaded pelo controller a partir do retorno de `create_for_customer`), em vez de reler `customer.accounts[0]`. Mantém o formato escalar do POST do Fluxo 1: `{customer_id, account_id, branch, account_number, status, status_reason, microcredit_eligible}`. `microcredit_eligible` é lido do `customer` já refreshed.

---

## 1.6 — Três rotas novas em `src/resources/customer.py` + `src/app.py`

Seguir o padrão resource→controller→repository→schema→dto. O decorator `@SchemaHandler.validate("x.json")` exige `payload` em kwargs (POST); GET não leva decorator.

1. **`POST /customers/{customer_id}/accounts`** — abre conta adicional. Resource `on_post_account(self, customer_id, payload)` com `@SchemaHandler.validate("post_customer_account.json")`. Controller `CustomerController.open_account(customer_id, payload)`:
   - Resolve titular (`CustomerNotFound` 404 se não existe — reusa `_get_customer_or_raise`).
   - **(finding 3 do 1º review + finding 3 do 2º review — D-ACC-RULE fixada, incluindo a borda vazia.)** Regra concreta de QIT001051: **recusa (409 `AdditionalAccountNotAllowed`) quando o titular não tem nenhuma conta não-terminal** — isto é, nenhuma conta em `{ACTIVE, PENDING, BLOCKED, REQUESTED}` (as seis status de `account_status` são `REQUESTED, PENDING, ACTIVE, BLOCKED, REJECTED, CLOSED`; terminais = `REJECTED`/`CLOSED`). Justificativa: um titular cujo cadastro/KYC foi recusado (todas as contas REJECTED) ou que encerrou tudo (CLOSED) não pode abrir conta adicional sem novo onboarding; abrir conta "por cima" de um cadastro recusado contorna o KYC. **Predicado implementável (evita a armadilha `all([]) == True`):**

     ```python
     NON_TERMINAL = {AccountStatus.REQUESTED, AccountStatus.PENDING, AccountStatus.ACTIVE, AccountStatus.BLOCKED}
     accounts = customer.accounts
     assert accounts, f"titular {customer.id} sem contas"   # invariante de construção; se falhar é bug (500)
     if not any(a.status.enumerator in NON_TERMINAL for a in accounts):
         raise AdditionalAccountNotAllowed(customer.id, "all accounts are REJECTED/CLOSED")
     ```

     **Borda "zero contas" fixada (finding 3):** após esta etapa um titular **sempre** nasce com ≥1 conta (o `create` abre a primeira na mesma transação), logo `customer.accounts` vazio é **impossível por construção**. O código usa `any(...)` (não `all(... terminal)`) justamente para que uma lista vazia **não** dispare QIT001051 por vacuidade; a lista vazia é tratada como **bug (assert → 500 QIT000500)**, não como 409 nem 404. Com ao menos uma conta não-terminal, abre normalmente.
   - Abre conta via `AccountRepository.create_for_customer` (reusa nascimento + evento). **Fonte de KYC fixada (finding 2):** a abertura de conta adicional **não re-roda `check_kyc`** — reusa o status de KYC já persistido no cadastro: `kyc_status = customer.kyc_status.enumerator` (a relationship `kyc_status` → `KycStatus.enumerator`, mesmo padrão de `account.status`). O onboarding de KYC/PLD rodou no registro; abrir uma segunda conta não é um novo onboarding, então reler o estado armazenado é o correto (e evita que uma mudança na lista restritiva do mock mude o desfecho de uma conta adicional de forma inconsistente com o cadastro). Status inicial: `self._initial_account_status(customer.person_type, kyc_status, age, is_pep)` — para NATURAL `age=self._age_in_years(customer.birth_date)` e `is_pep=customer.is_pep`; para LEGAL `age=None, is_pep=False`. Mesmo flush/outbox do create.
   - Schema `post_customer_account.json`: objeto vazio `{}` com `additionalProperties: false` (abertura não precisa de dados além do path), mantendo o decorator uniforme.
   - DTO: `creation_to_dict(customer, account)` com a conta recém-aberta. **201**.

2. **`GET /customers/{customer_id}/accounts`** — lista contas. Resource `on_get_accounts(self, customer_id)` sem decorator. Controller `list_accounts(customer_id)` → `CustomerNotFound` (404) ou `{"items": [AccountDTO.obj_to_dict(a) for a in customer.accounts]}` (ordenadas por `created_at`). **200**.

3. **`POST /customers/{customer_id}/relationships`** — cria vínculo PJ→PF. Resource `on_post_relationship(self, customer_id, payload)` com `@SchemaHandler.validate("post_customer_relationship.json")`. Controller `create_relationship(customer_id, payload)`:
   - `customer_id` é o lado **LEGAL** (a PJ). Resolve e valida `person_type == LEGAL` → senão **QIT001052** (`InvalidRelationship`, 422).
   - `payload`: `{ "natural_customer_id": <uuid>, "role": "PARTNER|ADMINISTRATOR|ATTORNEY" }`. Schema `post_customer_relationship.json`: `natural_customer_id` (string UUID, required), `role` (enum, required), `additionalProperties: false`.
   - Resolve `natural_customer_id` → precisa existir e ser NATURAL, senão **QIT001052** (422).
   - Insere em `customer_relationship` via **novo repositório `src/repositories/customer_relationship_repository.py`** (`create(legal_id, natural_id, role)` e opcional `exists(...)`), registrado em `repositories/__init__.py` (um repositório por entidade, como o resto do projeto).
   - **(finding 7 — status único.)** Duplicidade (mesma PK `legal+natural+role`) → `IntegrityError` no flush → traduzido para **QIT001052 (422)** com `description` "relationship already exists". **Um único código, um único status (422) para todas as falhas de vínculo** (lado errado de person_type, natural inexistente/não-NATURAL, duplicata). Nada de 409 (não sobrecarregar um código com dois status — "code is a contract"). A corrida é fechada pelo PK do banco; checagem prévia é opcional.
   - **201** com `CustomerDTO.relationship_to_dict(rel)` (método estático novo) → `{legal_customer_id, natural_customer_id, role, created_at}`.

Registrar as três no `src/app.py`, no bloco "A · Clientes e contas", logo após as rotas de `/customers/{customer_id}`:
```python
application.add_api_route("/customers/{customer_id}/accounts", customer_resource.on_post_account, methods=["POST"])
application.add_api_route("/customers/{customer_id}/accounts", customer_resource.on_get_accounts, methods=["GET"])
application.add_api_route("/customers/{customer_id}/relationships", customer_resource.on_post_relationship, methods=["POST"])
```

---

## 1.7 — `src/controllers/pix_key_controller.py`

- **Teto por `person_type`**: hoje `KEY_LIMIT = {Customer.INDIVIDUAL: 5, Customer.MEI: 20}`. Trocar para `{Customer.NATURAL: 5, Customer.LEGAL: 20}` e indexar por `account.customer.person_type` (não mais `.type`). EI/MEI é LEGAL (tem CNPJ) → teto de 20, coerente com o schema.
- **Chave CPF/CNPJ igual ao documento do titular** (`_key_value`): trocar a comparação contra `customer.cpf`/`customer.cnpj` por:
  - `key_type == PixKey.CPF`: titular deve ser NATURAL e `key_value == customer.document` → senão **QIT001041** `PixKeyNotOwned` (já existe).
  - `key_type == PixKey.CNPJ`: titular deve ser LEGAL e `key_value == customer.document` → senão **QIT001041**.
  (`document` é único por titular no v7; comparação direta.)
- **`_own_key_data`**: trocar `document = customer.cnpj if customer.type == Customer.MEI else customer.cpf` por `document = customer.document`, e `owner_person_type = PixKeyInquiry.LEGAL if customer.person_type == Customer.LEGAL else PixKeyInquiry.NATURAL`.
- **Remover todas as referências a `Customer.INDIVIDUAL` e `Customer.MEI`** (deixam de existir). QIT001041 já existe — **não recriar**.

---

## 1.8 — Tarifa por `fee_segment` em TEF, Pix e TED

### `src/models/fee.py`
Renomear a coluna `customer_type` → `customer_segment` (`Column(String, primary_key=True)`), casando com a tabela v7.

### `src/repositories/transfer_repository.py`
`current_fee(self, method, customer_type)` → `current_fee(self, method, customer_segment)`: filtrar `Fee.customer_segment == customer_segment`. O resto (ordenar por `effective_from` desc, `None → 0`) não muda. Atualizar o comentário que diz "só TEF consulta fee por customer.type" — agora os três trilhos consultam por `fee_segment`.

### `src/controllers/transfer_controller.py`
Trocar as três chamadas `current_fee(..., source.customer.type)` (TEF/PIX/TED) por `source.customer.fee_segment` (coluna gerada: `INDIVIDUAL` p/ NATURAL e EI/MEI; `BUSINESS` p/ SLU/LTDA). Comportamento conforme seeds v7 confirmados:
- **Pix** = **0** para INDIVIDUAL (PF e EI/MEI) **e** BUSINESS (ambos semeados 0).
- **TED** = 1000 centavos (ambos os segmentos).
- **TEF** = 100 centavos (ambos).

O app só **lê** `fee_segment` (derivado no banco) — sem lógica de classificação de segmento no Python. Nenhuma mudança nos seeds; nenhuma rota nova.

---

## 1.9 — Script de migração v6→v7 (`database/migrations/`)

Criar a pasta `database/migrations/` e um script **SQL puro** (`.sql`), executável via psycopg2 como o `database.sql` — mesma restrição de **não usar `%`**; mantém o ferramental existente e não introduz Alembic (que o projeto não usa). Nome: `database/migrations/v6_to_v7_titular.sql` + `database/migrations/README.md` documentando premissas e re-execução.

**(finding 8 — forma do ambiente-alvo FIXADA.)** O script roda contra um banco **com o DDL v7 já aplicado** (`database.sql` é a fonte da verdade, e já é v7 — não existem colunas `cpf`/`type`/`cnpj` nessa tabela), tendo os **dados de origem v6 carregados em tabelas de staging** que a migração lê. Isto elimina a contradição "rodar sobre colunas v6" vs. "colunas já v7". Tabelas de staging (criadas/populadas pela IF antes de rodar, documentadas no cabeçalho):

```
migration_source_customer (
    id UUID PRIMARY KEY,          -- id do customer v6
    cpf TEXT, cnpj TEXT,
    type TEXT,                    -- 'INDIVIDUAL' | 'MEI'
    name TEXT,
    birth_date DATE,
    is_pep BOOLEAN,
    annual_revenue BIGINT,
    kyc_status_id SMALLINT
)
migration_source_account (
    id UUID PRIMARY KEY,          -- id da conta v6
    customer_id UUID NOT NULL     -- aponta para migration_source_customer.id
    -- demais colunas de account continuam na tabela account v7 real (as contas já existem lá)
)
migration_pf_income (            -- D5
    mei_customer_id UUID PRIMARY KEY,  -- id v6 do MEI
    pf_annual_revenue BIGINT NOT NULL
)
```

> Nota de modelagem: as **contas em si** já vivem na tabela `account` v7 (com `customer_id` apontando para o id v6 do titular, já que o id é preservado para INDIVIDUAL e, para MEI, repontado — ver abaixo). `migration_source_customer` guarda os atributos v6 do titular que não cabem mais no formato v7 (`cpf`/`cnpj`/`type`). Todo `INSERT`/`UPDATE` lê staging e escreve `customer`/`account` v7.

**Transformação central — cada MEI do v6 vira DOIS titulares no v7:**

Para cada linha de `migration_source_customer` com `type='MEI'` (tem `cpf` e `cnpj`):
1. **Titular PF** (NATURAL): novo `customer` com `person_type='NATURAL'`, `document = cpf`, `name` (ver D-MIG-PFNAME), `birth_date`, `legal_nature=NULL`, `owner_customer_id=NULL`, `annual_revenue = migration_pf_income.pf_annual_revenue` (D5), `is_pep`, `kyc_status_id`. Id novo (`gen_random_uuid()`), guardado para ligar ao CNPJ.
2. **Titular CNPJ** (LEGAL/EI): `person_type='LEGAL'`, `legal_nature='EI'`, `document = cnpj`, `name = name` (razão social), `owner_customer_id =` id da PF do passo 1, `owner_person_type='NATURAL'`, `annual_revenue = <revenue v6 do MEI>` (a receita fica no CNPJ), `birth_date=NULL`. Pode **preservar o id v6** do MEI neste titular CNPJ (minimiza repontamento de conta).
3. **Conta e `annual_revenue` ficam no CNPJ.** `UPDATE account SET customer_id = <id_cnpj> WHERE customer_id = <id_v6_do_mei>` (se o id do CNPJ = id v6, vira no-op; só muda se tiver escolhido id novo). As contas que apontavam para o MEI passam a apontar para o CNPJ.
4. Para `type='INDIVIDUAL'`: um único titular NATURAL (`document = cpf`, `legal_nature=NULL`), **preservando o id** do titular (contas não precisam ser repontadas).

**D5 (premissa RFC) — renda da PF** é **dado de ENTRADA** via `migration_pf_income`. **Nunca** inventar nem usar zero: se faltar a linha para algum MEI, o script **aborta** com `RAISE EXCEPTION` nomeando o `mei_customer_id`. Documentar no cabeçalho que a tabela é pré-requisito.

**D6 (premissa RFC) — portabilidade da chave Pix CPF do MEI:** no v7 a conta MEI pertence ao CNPJ (LEGAL) e uma chave CPF não pode pertencer a titular LEGAL (regra 1.7). A chave CPF é **PORTADA para uma conta PF aberta na migração** (não excluída):
- A migração **abre uma conta CUSTOMER para o titular PF** do split (status ACTIVE, `balance=0`, `held_balance=0`), com `account_status_event` de nascimento (null→ACTIVE) e número de `account_number_seq`.
- As chaves `key_type='CPF'` ativas da conta do MEI são **repontadas**: `UPDATE pix_key SET account_id=<conta_pf> WHERE account_id=<conta_mei> AND key_type='CPF' AND status_id=<ACTIVE>`. Chaves CNPJ/EMAIL/PHONE/EVP ficam na conta do CNPJ.
- A conta PF nasce **sem saldo** (dinheiro fica no CNPJ); serve de lar da chave CPF. Documentar.

**Invariante de dinheiro:** o script **não cria/destrói `ledger_entry`** e **não altera `balance`/`held_balance`** das contas existentes; só **reponta `account.customer_id`** (MEI→CNPJ, possivelmente no-op) e abre a conta PF nova com saldo 0. A soma de saldos e o ledger são preservados por construção. **Asserção interna:** o script calcula `SUM(balance)` das contas CUSTOMER antes e depois e `RAISE EXCEPTION` se divergir ("nenhum centavo some").

**Idempotência / re-execução:** cada MEI/INDIVIDUAL processado é marcado em `migration_log (v6_customer_id UUID PRIMARY KEY, migrated_at TIMESTAMPTZ)`; cada passo usa `WHERE NOT EXISTS (...)` / `ON CONFLICT DO NOTHING`. Rodar 2× produz o mesmo estado. Documentar.

**Teste de migração (4.7)** — **desejável mas secundário** ao script correto. Se houver tempo, um teste de integração em `tests/integration/database/` que popula staging com dados "v6-like", roda o script e asserta: (a) cada MEI virou PF+CNPJ com `owner_customer_id` correto; (b) `SUM(balance)` antes == depois; (c) a chave CPF migrou para a conta PF e a conta MEI (agora CNPJ) não tem mais chave CPF; (d) rodar 2× não muda o resultado. **(finding 8)** Com o ambiente-alvo agora pinado (v7 DDL + staging), este teste é escrevível. Priorizar o script; o teste é bônus.

---

## Códigos de erro novos (item 4.1 — só os desta etapa)

Adicionar em `src/errors/custom_errors.py`, seguindo o padrão `QIException` (atributo de classe `code`, `__init__` montando `title/http_status/description/translation`). O `error_verification()` falha no boot se um código for duplicado — a faixa vai hoje até **QIT001049** (`InvalidScheduleDate`); 001050/51/52 estão livres (confirmado pela revisão). Contrato append-only — nenhum código v6 é removido/reaproveitado.

- **QIT001050 — `EiOwnerNotNatural`** (dono do EI não é pessoa natural). `http_status = 422`. `description`: "The owner of an EI must be a NATURAL person." `translation`: "O dono do EI precisa ser pessoa natural."
- **QIT001051 — `AdditionalAccountNotAllowed`** (abertura de conta adicional recusada). `http_status = 409`. `description`: "Cannot open an additional account for customer {customer_id}: {reason}." `translation`: "Não é possível abrir conta adicional para este titular." **Regra de disparo fixada (finding 3):** o titular **não tem nenhuma conta não-terminal** (nenhuma em `{ACTIVE, PENDING, BLOCKED, REQUESTED}`), avaliada por `any(...)` — a lista **vazia não dispara este erro** (é bug/500 por invariante de construção, nunca 409). `__init__(self, customer_id, reason)`.
- **QIT001052 — `InvalidRelationship`** (vínculo/relationship). **`http_status = 422` fixo, para TODAS as falhas de vínculo** (lado errado de person_type, natural inexistente/não-NATURAL, duplicata). `__init__(self, reason: str)` com `http_status=422` literal (sem parametrizar status; finding 7). `description`: "Invalid relationship: {reason}." `translation`: "Vínculo inválido."
- **QIT001041 — `PixKeyNotOwned`**: **já existe** — **não recriar**, só reusar em 1.7.

**NÃO criar QIT001053+** (microcrédito/fatura são Etapas futuras).

---

## Tratamento de erros por operação (concreto)

| Operação | Falha | Recuperável? | Resposta ao chamador | Log |
|---|---|---|---|---|
| POST /customers | schema inválido / tipo trocado / `is_pep` em LEGAL / owner em NATURAL etc. | fatal p/ a req | 400 QIT000001 (via SchemaHandler, **antes do banco**) | não (erro de cliente) |
| POST /customers | CPF/CNPJ dígito inválido | fatal | 422 QIT001003 / QIT001011 | não |
| POST /customers | EI com owner inexistente/não-NATURAL | fatal | 422 QIT001050 | não |
| POST /customers | documento já cadastrado (pré-checagem) | fatal | 409 QIT001010 | não |
| POST /customers | corrida de documento (UNIQUE no flush) | recuperável via rollback+traduzir | 409 QIT001010 | não; outro IntegrityError re-raise → 500 QIT000500 (log de bug) |
| POST /customers | KYC REJECTED / UNDERAGE (NATURAL) | não é erro | 201 com conta REJECTED (auditoria) | debug |
| POST .../accounts | titular inexistente | fatal | 404 QIT001008 | não |
| POST .../accounts | todas as contas do titular REJECTED/CLOSED | fatal | 409 QIT001051 | não |
| GET .../accounts | titular inexistente | fatal | 404 QIT001008 | não |
| POST .../relationships | legal não é LEGAL / natural inexistente ou não-NATURAL | fatal | 422 QIT001052 | não |
| POST .../relationships | vínculo duplicado (PK) | recuperável via rollback | 422 QIT001052 (already exists) | não |
| POST pix_key CPF/CNPJ | chave ≠ documento do titular | fatal | 422 QIT001041 | não |
| POST pix_key | teto de chaves atingido | fatal | 409 QIT001040 | não |
| transfer (TEF/PIX/TED) | leitura de fee sem linha | tolerável | fee = 0 (comportamento atual preservado) | não |
| migração | MEI sem renda PF em `migration_pf_income` | fatal | `RAISE EXCEPTION` (aborta a transação) | sim (mensagem nomeia o id) |
| migração | soma de saldos divergente antes/depois | fatal | `RAISE EXCEPTION` (rollback) | sim |

Regra geral herdada do projeto: `QIException` → resposta estruturada por `handlers.py`; qualquer exceção não-QI vira **500 QIT000500** com o erro real no log. Colunas geradas nunca são escritas — se o código tentar, o banco lança `IntegrityError`/`ProgrammingError` e isso é **bug** (500), não erro de cliente.

## Validação de cada entrada externa

- **POST /customers** — `person_type` (obrigatório, enum), `document` (obrigatório, 11 ou 14 dígitos via regex; DV no controller), `name` (1–255), `birth_date` (obrigatório **sse** NATURAL, formato data; existência real no controller → QIT001007), `legal_nature` (obrigatório **sse** LEGAL, enum), `owner_customer_id` (obrigatório **sse** EI, UUID; existência+NATURAL no controller → QIT001050; proibido em NATURAL e em SLU/LTDA → 400), `annual_revenue` (int, min 0, max 1e11 — **cap de sanidade da app**), `is_pep` (bool, **só NATURAL**; em LEGAL → 400). Campos fora do contrato → `additionalProperties:false` → 400. Resultado exato dos 8 payloads: ver tabela em 1.4.
- **PATCH /customers/{id}** — só `annual_revenue` (int 0–1e11, obrigatório). Tudo mais → 400.
- **POST /customers/{id}/accounts** — corpo `{}` (sem campos; `additionalProperties:false`). `customer_id` no path validado como UUID no controller (`parse_uuid` → 404 se malformado).
- **POST /customers/{id}/relationships** — `natural_customer_id` (UUID, obrigatório), `role` (enum PARTNER/ADMINISTRATOR/ATTORNEY, obrigatório). Lado LEGAL vem do path.

## Invariantes e dono da enforcement

- **`exposure_customer_id`/`fee_segment`/`microcredit_eligible` corretos** → dono: **o banco** (colunas geradas). O app nunca calcula; só lê (via `refresh`). Fonte única da verdade.
- **Dono do EI é NATURAL** → dono: **o banco** (FK composta `fk_ei_owner`); o controller **duplica** a checagem só para dar 422 QIT001050 amigável antes do flush.
- **PF↔PJ no relationship têm os person_types certos** → dono: **o banco** (FKs compostas + CHECK); o controller valida antes para dar 422 QIT001052.
- **Documento único** → dono: **o banco** (UNIQUE nomeada `ux_customer_document`); o controller faz pré-checagem e trata a corrida no `IntegrityError` (mapa determinístico, finding 4), com teste de integração travando 409 QIT001010.
- **`is_pep` só em NATURAL** → dono compartilhado: **o schema JSON** barra `is_pep` em LEGAL (400) e o **banco** (`ck_pep_natural`) é a rede de segurança.
- **Chave Pix CPF/CNPJ == documento do titular** → dono: **o controller** (`PixKeyController._key_value`); regra de produto, sem CHECK no banco.
- **Teto de chaves por conta** → dono: **o controller** sob lock da conta (igual v6).
- **Dinheiro preservado na migração** → dono: **o script** (asserção `SUM(balance)` antes/depois + ledger intocado).

## Testabilidade

- **Unit (sem banco):** `is_valid_cpf`/`is_valid_cnpj` (já cobertos); a ramificação dos JSON Schemas é testável carregando o schema e validando os 8 payloads da tabela 1.4.
- **Integração (Postgres real via `DbUtils`):** criação de NATURAL, EI (owner NATURAL válido/ inválido → QIT001050), SLU, LTDA; documento duplicado → QIT001010; `fee_segment`/`microcredit_eligible` lidos corretos (PF e EI → INDIVIDUAL, SLU/LTDA → BUSINESS; revenue 36000000 → eligible); conta adicional (POST abre; POST com todas as contas REJECTED/CLOSED → QIT001051; GET lista); relationship (criação, person_type errado → 422, duplicata → 422); Pix (teto 5 NATURAL / 20 LEGAL; chave CPF/CNPJ ≠ documento → QIT001041); tarifa (Pix PF e EI = 0, TED = 1000, TEF = 100, lidos por `fee_segment`). **Fluxo 1 da RFC**: cadastrar PF, EI/MEI, SLU, LTDA e abrir conta, ponta a ponta.
- **Migração (desejável):** staging v6-like → roda script → asserts de split, dinheiro, chave Pix, idempotência.
- **Harness:** `tests/utils/payload_generator.py` (`create_customer_payload`) usa vocabulário v6 (`cpf`/`cnpj`/`type`) — **precisa ser reescrito** para o payload v7, senão os testes existentes de conta/pix/transfer/cartão que criam clientes por ele quebram. O design assume que `tests/utils/object_generator.py`, se existir e emitir clientes, também precisa de atualização (a revisão não confirmou seu conteúdo — o implementador deve checar e atualizar o que criar `Customer` com vocabulário v6). Este é um ponto de propagação importante e parte do custo da etapa.

**Design hard-to-test?** Não. A única área delicada é a migração SQL; mantê-la como script idempotente com asserções internas (`RAISE EXCEPTION`) a torna testável comparando estado antes/depois.

---

## Decisões em aberto (para o planner/usuário)

As ambiguidades que a revisão marcou como bloqueantes foram **fechadas** nesta revisão (D-ACC-RULE, D-DTO-SHAPE, D-REL-STATUS, D-MIG-SHAPE). O que resta são confirmações de baixo risco, não bloqueios de implementação:

- **D-EI-OWNER (confirmação):** owner inexistente → QIT001050 (vs. `CustomerNotFound` 404). Escolhido QIT001050 pela semântica "EI sem dono natural válido". Fácil de inverter se o produto preferir 404.
- **D-KYC-PJ (limitação de mock — finding 9):** `check_kyc` recebe o `document`; o mock (`KYC_REJECTED_CPFS`, CPFs de 11 dígitos) **nunca casa um CNPJ**, logo **todo titular LEGAL é auto-aprovado no KYC**. Comportamento documentado e aceitável para esta etapa. Se um teste de rejeição de PJ for desejado, adicionar `KYC_REJECTED_DOCUMENTS` ao mock; fora de escopo por ora.
- **D-PATCH (confirmação):** PATCH restrito a `annual_revenue` (sem trocar person_type/document/legal_nature). Confirmar que não há requisito de "corrigir tipo" por PATCH.
- **D-MIG-PFNAME:** o nome do titular PF derivado de um MEI. O v6 só tem um `name` (que vira a razão social do CNPJ). Decisão proposta: usar o **mesmo `name`** para a PF (empresário individual costuma ter nome civil = base da razão social) **a menos** que `migration_pf_income` (ou outra tabela de staging) traga um `pf_name` explícito. Confirmar se a IF fornece o nome civil da PF separadamente; se sim, o script lê de lá. Baixo risco (campo informativo, não entra em CHECK/FK).

Nenhuma decisão foi resolvida com valor inventado: onde a regra existia na RFC/premissas, foi fixada; onde é só confirmação de produto, está marcada.

---

## Respostas à revisão — 2º ciclo (`design-review.json` / `design-review.md`, Revisão 3)

| # | Sev | Resolução |
|---|---|---|
| 1 | MEDIUM | **Corrigido.** §1.5 passo 5 agora escreve a assinatura concreta `_initial_account_status(self, person_type, kyc_status, age=None, is_pep=False)` com o curto-circuito `if person_type == Customer.LEGAL: return ACTIVE, None` **antes** de qualquer `age <`, de modo que `age=None` em LEGAL nunca é comparado. §1.6 referencia a mesma assinatura e diz o que o controller passa (NATURAL: age/is_pep reais; LEGAL: `age=None, is_pep=False`). |
| 2 | MEDIUM | **Fechado.** §1.6 route 1 fixa: a abertura de conta adicional **não re-roda `check_kyc`**; reusa `kyc_status = customer.kyc_status.enumerator` (status de KYC já persistido no cadastro). Justificativa escrita (não é novo onboarding; evita divergência com o cadastro se a lista restritiva mudar). |
| 3 | MEDIUM | **Fechado.** §1.6 route 1 troca o predicado para `any(a.status.enumerator in NON_TERMINAL ...)` + `assert accounts`. A borda "zero contas" é explícita: impossível por construção (titular nasce com ≥1 conta); lista vazia → bug/500 via assert, **nunca** QIT001051 por vacuidade. Descrição do QIT001051 atualizada. |
| 4 | MEDIUM | **Fechado.** §1.5 passo 7: em vez de adivinhar `customer_document_key`, a etapa **nomeia a UNIQUE explicitamente** no `database.sql` (`CONSTRAINT ux_customer_document UNIQUE (document)` — única exceção de DDL fora da migração) tornando o mapa Python determinístico, **e** exige um teste de integração que força documento duplicado e asserta 409 QIT001010 (não 500). Fallback (confirmar `\d customer` + teste) documentado caso o DDL não possa mudar. Overview, fatos do schema e Invariantes atualizados. |
| 5 | NIT | **Documentado.** §1.5 DTO: a lista `accounts` embutida em `GET /customers/{id}` é projeção fina **deliberada** (sem saldos) vs. `AccountDTO.obj_to_dict` do endpoint dedicado `GET /customers/{id}/accounts` (completo). Motivo (visão de titular vs. visão de conta) e alternativa rejeitada escritos. |
| 6 | NIT | **Corrigido.** §1.5: decisão dura — **remover `MICROCREDIT_REVENUE_CAP` e as duas computações `annual_revenue <= CAP`** do `customer_controller.py`; elegibilidade é read-only de `customer.microcredit_eligible`. Sem constante residual. |

## Respostas à revisão — 1º ciclo (`design-review.json`)

| # | Sev | Resolução |
|---|---|---|
| 1 | HIGH | **Corrigido.** Removido `is_pep_na` do snippet; ramo NATURAL proíbe exatamente `legal_nature` e `owner_customer_id`. `is_pep` **proibido no ramo LEGAL** (400) — decisão fixada em 1.4; o `ck_pep_natural` do banco é rede de segurança. |
| 2 | HIGH | **Corrigido.** (a) Declarado que `annual_revenue` max 1e11 é cap de sanidade da **aplicação**, não do schema. (b) Adicionada tabela de 8 payloads representativos com resultado exato e cláusula decisora em 1.4; casos extras pinados. |
| 3 | MEDIUM | **Fechado (Option B).** QIT001051 dispara (409) quando **todas** as contas do titular estão REJECTED/CLOSED (nenhuma não-terminal). Sinal lido = `account.status.enumerator`. Regra concreta e implementável; código não vira dead code nem regra inventada. |
| 4 | MEDIUM | **Fechado.** GET `/customers/{id}`: **mantém `account_id`** (conta mais antiga, `accounts[0]`) **e adiciona** `accounts` (lista). Sem hedge. Minimiza quebra dos testes do Fluxo 1. |
| 5 | MEDIUM | **Corrigido.** Relationship `accounts` declarado com `order_by="Account.created_at"`; `creation_to_dict(customer, account)` recebe o objeto fresco do `create_for_customer`, não relê `accounts[0]`. |
| 6 | MEDIUM | **Corrigido.** Sequência explícita documentada em 1.5: build (no_autoflush) → `flush` dentro do try/except → `refresh` só no sucesso (nunca antes) → outbox → commit. `update_revenue` ganha `flush`+`refresh` espelhando o create. |
| 7 | MEDIUM | **Fechado.** QIT001052 = **422 fixo** para todas as falhas de vínculo, inclusive duplicata. `InvalidRelationship.__init__(reason)` com `http_status=422` literal. Alternativa 409 eliminada. |
| 8 | MEDIUM | **Fechado.** Migração roda contra **DDL v7** com dados v6 em **tabelas de staging** (`migration_source_customer`, `migration_source_account`, `migration_pf_income`). INSERT/UPDATE lê staging, escreve v7. `SUM(balance)` assertível; teste 4.7 escrevível. |
| 9 | NIT | **Documentado.** D-KYC-PJ: PJ sempre aprova no mock (CNPJ nunca casa `KYC_REJECTED_CPFS`). Opção de `KYC_REJECTED_DOCUMENTS` registrada como fora de escopo. |
| 10 | NIT | **Endereçado.** Nome `customer_document_key` é inferência do auto-nome Postgres; o implementador **confirma com `\d customer`** antes de hardcodar; mecanismo (`error.orig.diag.constraint_name`) já existe no `_violated_document`. |
| 11 | NIT | **Corrigido.** `creation_to_dict` lê `microcredit_eligible` **após** o `refresh` (passo 8 da sequência em 1.5), nunca stale/None. Amarrado ao finding 6. |

Fatos reconfirmados contra o código real nesta revisão: seeds de `fee` v7 (TEF 100 / PIX 0 / TED 1000 em ambos os segmentos — lidos em `database.sql`); `update_revenue` atual não tem `flush` (confirmado no repositório); `_violated_document` lê `error.orig.diag.constraint_name` (confirmado no controller v6); `create_for_customer` usa `no_autoflush` com o comentário sobre manter o INSERT dentro do `try` (confirmado no `account_repository.py`).
