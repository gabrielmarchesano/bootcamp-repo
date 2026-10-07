# Verificação — Etapa 0: Estabilizar a main

Worktree: `c:\Users\Gustavo\Desktop\RFC\bootcamp-repo\.worktrees\etapa-0-estabilizar`
Branch: `etapa-0-estabilizar`
Ambiente: Windows, Python 3.11.9, venv em `.venv/` (git-ignored), Docker 29.8.2 + Compose v5.5.1 DISPONÍVEIS.

## O que foi implementado (itens 0.1–0.6)

- **0.1** `src/resources/__init__.py` reescrito: exporta as 10 classes de resource que `src/app.py` importa
  (`AccountResource, CardResource, CardAuthorizationResource, CreditWalletResource, CustomerResource,
  HealthCheckResource, PixResource, TedResource, TransferResource, WebhookResource`). O antigo conteúdo
  (lista de models) foi movido para `models/__init__.py` conforme 0.2.
- **0.2** `src/models/__init__.py` completado com todos os enums e models das tabelas: `PixKeyStatus,
  CreditWalletStatus, CardStatus, CardAuthorizationStatus, InvoiceStatus, PixKey, PixKeyStatusEvent,
  PixKeyInquiry, CreditWallet, CreditWalletStatusEvent, Card, CardStatusEvent, CardAuthorization,
  CardAuthorizationStatusEvent, CardAuthorizationEvent, Invoice, InvoiceStatusEvent, InvoiceItem`.
- **0.3** `git mv src/models/pix_key_injury.py src/models/pix_key_inquiry.py`. A classe já era `PixKeyInquiry`,
  sem mudança interna. `grep pix_key_injury src` → nada.
- **0.4** `src/repositories/__init__.py`: adicionados `PixKeyRepository, CardRepository,
  CardAuthorizationRepository, CreditWalletRepository, InvoiceRepository, CalendarRepository`
  (nomes de classe confirmados abrindo cada arquivo).
- **0.5** `src/controllers/transfer_controller.py`: implementados `create_pix` (KEY/MANUAL, on-us 201 /
  externo 202), `create_pix_reversal` (REVERSAL, e2e começando em `D`, 202), `create_ted` (imediata na
  janela do STR / agendada SCHEDULED sem débito) e `cancel` (SCHEDULED → CANCELED; outro status → 409).
  Adicionado o constante de módulo `NIGHT_LIMIT = 100_000` (o `_check_night_limit` referenciava um nome
  inexistente — `NameError`). Adicionado helper `generate_str_control_number` em `transfer_repository.py`.
  Corrigido também o uso de `OutboxEvent.TRANSFER_COMPLETED` (atributo inexistente no model → `AttributeError`
  em todo TEF) para `OutboxEvent.OUTGOING_TEF`, que é a constante já definida para o trilho TEF.
- **0.6** `src/repositories/incoming_transfer_repository.py::create` passou a aceitar
  `pix_transfer_type` e `original_transfer_id` e a persistir também `receiver_pix_key`, `pix_message`
  e `original_transfer_id` — corrige o `TypeError` que o `webhook_controller.received()` provocava.
- **Schemas (parte de 0.5):** criados `post_pix_transfer.json`, `post_pix_reversal.json`,
  `post_ted_transfer.json`, `post_webhook_str.json`, `get_pix_key_lookup.json`, `post_pix_key.json`
  (as rotas Pix/TED/webhook-STR do `app.py` já os referenciam; sem eles o `@SchemaHandler.validate`
  estoura antes do controller). Card/credit/invoice schemas ficam fora de escopo da Etapa 0.
- **0.7** `database/database.sql` NÃO foi alterado por este trabalho (ver bloqueio abaixo).

## Verificação executada

(a) **`import app` a partir de `src/`** — OK, sem `ImportError`:
```
python -c "import sys; sys.path.insert(0,'src'); import os; os.environ.setdefault('DATABASE_URL', ...);
           os.environ.setdefault('INTERNAL_TOKEN','default_token'); import app; print('APP OK')"
→ APP OK
```
Isto exercita a cadeia real de boot resources → controllers → repositories → models e prova 0.1–0.4,
a renomeação 0.3 e a correção de `NIGHT_LIMIT`/`OUTGOING_TEF`.

(c) **Nenhum import quebrado** em `models/__init__.py`, `resources/__init__.py`, `repositories/__init__.py`:
`pytest tests --collect-only -q` → **130 testes coletados, 0 erros de import/coleta**.
(Foi necessário instalar `tzdata` no venv — Windows não traz a base IANA de fusos, e
`tests/integration/transfer/test_transfer_ted.py` usa `ZoneInfo("America/Sao_Paulo")` no import.
Isso é dependência do ambiente de teste, não do código-fonte.)

(d) **Renomeação** confirmada: `src/models/pix_key_inquiry.py` existe; `src/models/pix_key_injury.py` NÃO existe.

(b) **Suíte completa (`pytest tests -q`) — NÃO atinge 130/130. 17 passaram, 111 falharam, 2 skipped.**
Docker/Postgres ESTÁ disponível e a stack subiu saudável (`docker compose up -d --build`;
db e api `healthy`; `/health_check` → 204). A causa das 111 falhas NÃO são os itens 0.1–0.6:
é um conflito de schema fora do escopo da Etapa 0 (ver abaixo). Exemplo de falha (criação de cliente,
que nem toca no meu código):
```
GET/POST /customers → 500 QIT000500
log da API: psycopg2.errors.UndefinedColumn: column customer.cpf does not exist
```

## BLOQUEIO (impede 130/130) — conflito entre `database/database.sql` e o código

O `database/database.sql` da worktree (a modificação "v7" pré-aplicada, que aparece como `M` no git e que
a tarefa manda NÃO alterar) define a tabela `customer` com `person_type/document/legal_nature/...`
e **sem as colunas `cpf` e `type`**. Verificado no banco em execução:
```
columns de customer: id, person_type, document, name, birth_date, legal_nature, owner_customer_id,
owner_person_type, exposure_customer_id, fee_segment, annual_revenue, ...  (sem cpf, sem type)
```
Mas TODO o código em `src/` (models, repositories, controllers) é escrito para o schema ANTIGO:
`src/models/customer.py` tem `cpf = Column(CHAR(11), ...)` e `type IN ('INDIVIDUAL','MEI')`;
`customer_repository.get_by_cpf` consulta `customer.cpf`. Logo, qualquer rota que toque em cliente/conta
quebra com `column customer.cpf does not exist` — e como todos os testes de integração criam uma conta
primeiro, 111/130 caem por isso, em TODOS os domínios (TEF, Pix, TED, webhook, cartões, schema-rules),
não só nos itens da Etapa 0.

- A versão **commitada (HEAD)** de `database.sql` TEM `customer.cpf` e `type IN ('INDIVIDUAL','MEI')`
  (compatível com os models), **porém** nem sequer carrega do zero: o seed de contas internas viola
  `account.customer_id NOT NULL` (`psql:/tmp/head.sql:854: ERROR: null value in column "customer_id"
  of relation "account"`), enquanto `src/models/account.py` trata `customer_id` como anulável
  (conta INTERNAL não tem cliente).
- A versão **da worktree** carrega limpa (a stack subiu), mas tem o `customer` incompatível com o código.

Ou seja: **nenhuma das duas versões de `database.sql` é compatível com o código-fonte desta worktree**,
em sentidos opostos. Reverter/alterar `database.sql` seria a única forma de chegar a 130/130, e isso é
exatamente o que o item 0.7 proíbe ("NÃO alterar database/database.sql"). Essa é uma decisão de
produto/arquitetura (muda o contrato do modelo de dados) fora da alçada da Etapa 0 — por isso o passo
foi sinalizado com `warning` em vez de eu decidir sozinho.

### 17 testes que passaram
São os que não exigem o schema de `customer`/`account` compatível (ex.: health check, validações de schema
que falham antes de tocar no banco, alguns 400/404 de parsing). O detalhamento completo (111 nomes) está no
resumo do `pytest tests -q`.

## Estado do ambiente ao final
- Stack Docker deixada de pé e saudável; banco `bootcamp` recarregado a partir do próprio
  `database/database.sql` da worktree (schema sobe do zero sem erro — confirma a parte de 0.7 que diz
  respeito ao schema LOADAR; o que falha é a compatibilidade com o código, não a carga).
- `.venv/` e artefatos temporários não versionados; nenhum arquivo fora do conjunto pretendido foi tocado
  (`database.sql` continua com a modificação pré-existente, intacta).
