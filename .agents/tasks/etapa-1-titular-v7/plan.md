# Plano de Implementacao — Etapa 1: Modelo de titular v7

Plano enxuto. Fluxos ja estao na RFC/PDF; aqui so arquivos, ORDEM e pontos de atencao.
Trabalhar SOMENTE na worktree `c:\Users\Gustavo\Desktop\RFC\bootcamp-repo\.worktrees\etapa-1-titular-v7`
(branch `etapa-1-titular-v7`). NAO tocar `database/database.sql` (ja e o v7, commit e6c9fe7).
Git sempre com `git -C c:\Users\Gustavo\Desktop\RFC\bootcamp-repo\.worktrees\etapa-1-titular-v7`.

## Sanity check (confirmado nesta exploracao)
- `database/database.sql` CONTEM `fluxos v7` (linha 2) e `customer_segment` (tabela `fee`, PK). OK.
- `database/database.sql` NAO contem o caractere de porcentagem. OK (regra dura mantida — nao editar o arquivo).
- Worktree existe, branch `etapa-1-titular-v7` em `e6c9fe7`, a partir de `feat/backlog-v7`. OK.

## Ambiente / como verificar (do README)
- API + banco sobem no Docker; testes rodam no host contra a API no container.
- `database/database.sql` roda UMA vez (nascimento do banco). Para recarregar schema v7:
  `docker compose down -v; docker compose up` (o `-v` apaga o volume e recria do zero).
- Testes: com venv ativa e API `(healthy)`, rodar `pytest` (raiz da worktree).
  Rodar um alvo: `pytest -v tests/integration/customer`.
- `tests/utils/db_utils.py` recarrega o schema via psycopg2 (dai a regra do porcentagem).
- Verificacao de cada item abaixo = subir o banco v7 e rodar o `pytest` indicado (grep NAO e verificacao).

## Vocabulario v7 (referencia rapida, da tabela `customer` no database.sql)
- `person_type` ∈ {NATURAL, LEGAL}; `document` VARCHAR(14) UNIQUE (CPF 11 / CNPJ 14, so digitos).
- `legal_nature` ∈ {EI, SLU, LTDA} (so LEGAL); `owner_customer_id` + `owner_person_type='NATURAL'` so quando EI.
- Colunas GERADAS (somente-leitura, nunca gravar): `exposure_customer_id`, `fee_segment` (INDIVIDUAL/BUSINESS), `microcredit_eligible` (annual_revenue <= 36000000).
- `account.customer_id` deixou de ser UNIQUE (N contas por titular). FK UNIQUE do documento = constraint inline -> nome autogerado do Postgres `customer_document_key`.

---

## ORDEM DE IMPLEMENTACAO

- [ ] 1. (1.2) Reescrever o model `Customer` para o v7.
      Remover `cpf`/`type`/`cnpj` e as constantes `INDIVIDUAL`/`MEI`. Adicionar `person_type`, `document`,
      `legal_nature`, `owner_customer_id`, `owner_person_type`. Mapear `exposure_customer_id`, `fee_segment`,
      `microcredit_eligible` com `server_default=FetchedValue()` (sqlalchemy) e NUNCA gravar nelas.
      Trocar o relationship `account` de `uselist=False` para `uselist=True` (lista). Em `src/models/account.py`
      REMOVER o `unique=True` de `customer_id` (v7 permite N contas por titular).
      Files: src/models/customer.py, src/models/account.py
      Verify: `python -c "import sys; sys.path.insert(0,'src'); import models"` sem erro de import/mapper (ou primeiro `pytest` que importe os models).

- [ ] 2. (1.3) Criar o model `CustomerRelationship` e registrar.
      Criar `src/models/customer_relationship.py` espelhando a tabela `customer_relationship` do v7: PK composta
      (`legal_customer_id`, `natural_customer_id`, `role`), colunas `legal_person_type` default 'LEGAL',
      `natural_person_type` default 'NATURAL', `role` ∈ {PARTNER, ADMINISTRATOR, ATTORNEY}, `created_at`.
      Registrar o import em `src/models/__init__.py` (bloco "Cliente e conta").
      Files: src/models/customer_relationship.py, src/models/__init__.py
      Verify: import dos models sem erro de mapper (ver item 1).

- [ ] 3. (Fee) Alinhar o model `Fee` ao v7.
      Renomear a coluna `customer_type` -> `customer_segment` em `src/models/fee.py` (o v7 usa `customer_segment`).
      Files: src/models/fee.py
      Verify: coberto pela suite de transfer no item 10 (lookup de tarifa).

- [ ] 4. (4.1) Erros novos em `src/errors/custom_errors.py`.
      Proximo numero livre = QIT001050. Criar seguindo o padrao das classes existentes (title/code/http_status/
      description/translation): QIT001050 (dono do EI nao e PF), QIT001051 (regra de conta adicional),
      QIT001052 (regra de vinculo, http_status=422). QIT001041 (chave Pix CPF/CNPJ != document) JA EXISTE como
      `PixKeyNotOwned` — reusar, nao recriar. NAO criar QIT001053+.
      Files: src/errors/custom_errors.py, src/errors/__init__.py (exportar as 3 novas classes)
      Verify: `error_verification` no start nao acusa codigo repetido; coberto quando a API sobe (itens seguintes).

- [ ] 5. (1.4) Reescrever os schemas JSON de cliente por `person_type`.
      `post_customer.json`: campos v7 (`person_type`, `document`, `name`, `annual_revenue`, opcionais `birth_date`,
      `legal_nature`, `owner_customer_id`, `is_pep`). Condicionais no estilo if/then/else ja usado no arquivo atual:
      `birth_date` obrigatorio/presente SO quando NATURAL; `legal_nature` SO quando LEGAL; `owner_customer_id` SO
      quando `legal_nature=EI`; `is_pep` so NATURAL (proibido/efetivo-falso em LEGAL). Rejeicao de schema = 400 ANTES
      de qualquer consulta ao banco (ja e o comportamento do SchemaHandler). `patch_customer.json` segue so com
      `annual_revenue` (sem alteracao de forma, confirmar coerencia).
      Files: src/schemas/post_customer.json, src/schemas/patch_customer.json
      Verify: `pytest -v tests/integration/customer/test_customer_create.py` (apos itens 6-7 e fixtures do item 11).

- [ ] 6. (1.5) Adaptar repository + DTO de cliente ao v7.
      `customer_repository.py`: `create` grava `person_type`, `document`, `name`, `birth_date`, `legal_nature`,
      `owner_customer_id`/`owner_person_type`, `annual_revenue`, `kyc`, `is_pep` — NAO gravar `microcredit_eligible`/
      `fee_segment`/`exposure_customer_id` (geradas). Trocar `get_by_cpf`/`get_by_cnpj` por `get_by_document`.
      `customer_dto.py`: expor `person_type`/`document`/`legal_nature` no lugar de `cpf`/`type`/`cnpj`; `account`
      agora e lista — na resposta de criacao usar a conta recem-criada; em `obj_to_dict` escolher conta de forma
      deterministica (ex. a mais antiga por `created_at`) ou expor lista, mantendo coerencia com o contrato.
      Files: src/repositories/customer_repository.py, src/dtos/customer_dto.py
      Verify: coberto por `pytest -v tests/integration/customer`.

- [ ] 7. (1.5) Adaptar `customer_controller.py` ao v7.
      Validar digito verificador por `person_type`: `is_valid_cpf` (11) se NATURAL, `is_valid_cnpj` (14) se LEGAL
      (utils ja existem em `src/utils/document_number.py`). Dono do EI deve ser PF -> senao QIT001050. Elegibilidade:
      NAO calcular/gravar `microcredit_eligible` (coluna gerada); apos o INSERT fazer `flush()` + `refresh(customer)`
      (ou `session.refresh`) para LER as colunas geradas. Duplicidade de documento: substituir o dict v6
      `UNIQUE_DOCUMENT_CONSTRAINTS` ({customer_cpf_key, customer_cnpj_key}) pelo nome real do v7 — a UNIQUE inline de
      `document` autogera `customer_document_key`; mapear essa violacao para 409 (`CustomerAlreadyExists`). Se o nome
      nao casar em runtime, detectar por IntegrityError/`UniqueViolation` em vez de hardcode fragil. Fluxo 1 da RFC
      ponta a ponta para PF, EI/MEI, SLU, LTDA.
      Files: src/controllers/customer_controller.py
      Verify: `pytest -v tests/integration/customer`.

- [ ] 8. (1.6) 3 rotas novas de titular: contas adicionais e vinculos.
      Em `src/resources/customer.py` adicionar handlers; registrar em `src/app.py` (bloco "A · Clientes e contas").
      Criar schemas de request onde houver corpo. Seguir o padrao resource -> controller -> repository -> dto.
        - POST `/customers/{customer_id}/accounts`: abre conta adicional reusando `AccountRepository.create_for_customer`;
          KYC reutiliza o `kyc_status` atual do titular; QIT001051 quando regra violada (definir gatilho DETERMINISTICO
          e coerente com o dominio, ex. titular sem conta ACTIVE / status que impede nova conta — documentar no codigo).
        - GET `/customers/{customer_id}/accounts`: lista as contas do titular, ordenacao deterministica por `created_at`.
        - POST `/customers/{customer_id}/relationships`: cria vinculo PARTNER/ADMINISTRATOR/ATTORNEY (model do item 2);
          QIT001052 (422) quando violado (ex. legal nao e LEGAL, natural nao e NATURAL, par duplicado).
      Novos metodos de repository: `AccountRepository.list_by_customer` e um `CustomerRelationshipRepository` (ou
      metodos no `CustomerRepository`), coerente com o estilo existente.
      Files: src/resources/customer.py, src/app.py, src/controllers/customer_controller.py,
      src/repositories/account_repository.py, src/repositories/customer_repository.py,
      src/schemas/post_customer_account.json (se houver corpo), src/schemas/post_customer_relationship.json,
      src/dtos/customer_dto.py (dto de conta/vinculo), docs/api-contract.md (opcional, registrar rotas)
      Verify: subir banco v7; `pytest` da suite de customer verde; se adicionar testes das rotas novas, rodar o arquivo.

- [ ] 9. (1.7) Teto de chaves Pix por `person_type` + chave CPF/CNPJ = `document`.
      `src/controllers/pix_key_controller.py`: `KEY_LIMIT` por `person_type` (NATURAL=5, LEGAL=20) no lugar de
      `{Customer.INDIVIDUAL, Customer.MEI}`. Exigir que chave CPF/CNPJ seja igual ao `customer.document`
      (`_key_value` e `_own_key_data`), levantando QIT001041 (`PixKeyNotOwned`) quando diferente. REMOVER toda
      referencia a `Customer.INDIVIDUAL`/`Customer.MEI` e leituras `customer.cpf`/`.cnpj`/`.type`
      (usar `person_type`/`document`; `owner_person_type` do inquiry derivado de `person_type`).
      Files: src/controllers/pix_key_controller.py
      Verify: `pytest -v tests/integration/pix` (ou arquivos de pix_key) verde.

- [ ] 10. (1.8) Tarifa por `fee_segment` + CORRIGIR bug critico do Pix manual.
      `src/repositories/transfer_repository.py`: `current_fee(method, segment)` consulta `Fee` por `customer_segment`
      (renomeado no item 3). `src/controllers/transfer_controller.py`: nas 3 chamadas de `current_fee` (TEF ~l.160,
      PIX ~l.319, TED ~l.496) passar `source.customer.fee_segment` no lugar de `source.customer.type`.
      BUG CRITICO (CAMINHO DE DINHEIRO): `_pix_manual_fields` (~l.623) le `holder.cnpj if holder.type == Customer.MEI
      else holder.cpf` — atributos v6 que nao existem no v7 (estoura 500). Reescrever para comparar
      `target["document"]` com `holder.document` (o `document` ja e CPF ou CNPJ conforme `person_type`).
      Files: src/repositories/transfer_repository.py, src/controllers/transfer_controller.py
      Verify: `pytest -v tests/integration/transfer tests/integration/pix` — tarifas (PIX=0, TEF=100, TED=1000) e Pix manual verdes.

- [ ] 11. (Auditoria) Varrer TODO o `src/` por vocabulario v6 remanescente.
      Procurar `.cpf`/`.cnpj`/`.type` em objetos `Customer`, `Customer.INDIVIDUAL`, `Customer.MEI`, `get_by_cpf`,
      `get_by_cnpj`, e usos de `customer.account` como objeto unico (agora e lista). Pontos ja mapeados:
      customer_dto, customer_repository, customer_controller, pix_key_controller, transfer_controller
      (cobertos acima) — confirmar que NENHUM resto ficou. Reescrever para `person_type`/`document`.
      Files: varredura em src/** (corrigir onde achar)
      Verify: suite completa `pytest` nao acusa `AttributeError` de atributo v6; API sobe sem 500 nesses caminhos.

- [ ] 12. (Testes) Migrar fixtures/geradores e asserts para v7.
      `tests/utils/payload_generator.py` `create_customer_payload`: emitir `person_type`/`document`/`legal_nature`
      no lugar de `cpf`/`type`/`cnpj`; onde criava `type=MEI`, no v7 vira o par PF(NATURAL)+CNPJ(LEGAL,EI) —
      adaptar preservando a INTENCAO (helper que cria os dois titulares e vincula via `owner_customer_id`).
      `tests/utils/object_generator.py` `create_active_account(customer_type=...)` -> parametro `person_type`.
      `tests/utils/request_generator.py`: adicionar helpers para as rotas novas do item 8 se os testes usarem.
      `tests/integration/customer/test_customer_create.py`: reescrever os testes v6 (`test_creates_mei_with_cnpj`,
      `test_schema_requires_cnpj_for_mei...`, `test_refuses_duplicated_cpf`, etc.) para a regra v7 equivalente.
      `tests/integration/database/test_schema_rules.py`: o INSERT raw usa colunas v6 (`cpf`,`type`) -> trocar por
      colunas v7 (`person_type`,`document`,...). Buscar todos os chamadores de `create_customer_payload`/
      `create_active_account` e ajustar.
      Files: tests/utils/payload_generator.py, tests/utils/object_generator.py, tests/utils/request_generator.py,
      tests/integration/customer/*.py, tests/integration/database/test_schema_rules.py, demais chamadores
      Verify: `docker compose down -v; docker compose up` (schema v7) e depois `pytest` com a suite VERDE.
      Esperado: os 2 skips de TED (janela STR 6h30-17h dia util) permanecem — nao e falha.

- [ ] 13. (1.9) Script de migracao v6->v7 em `database/migrations/`.
      Criar a pasta `database/migrations/` e um script idempotente/re-rodavel. Cada MEI do v6 vira DOIS titulares no
      v7: a PF (`document`=CPF, NATURAL) e o CNPJ (LEGAL, `legal_nature=EI`, `owner_customer_id`->PF). Conta e
      `annual_revenue` ficam no CNPJ. Asserir/relatar que a soma de dinheiro (contas, saldos, ledger) e IDENTICA
      antes e depois. D5: a renda da PF e dado de ENTRADA (staging) informado pela IF ANTES da migracao; se faltar
      a renda de alguma PF, ABORTAR com erro claro (nao assumir zero) — documentar no cabecalho. D6: chave Pix CPF
      da conta do MEI e PORTADA para uma conta PF aberta na migracao (nao excluida) — documentar.
      Files: database/migrations/ (novo diretorio + script, ex. `v6_to_v7_titular.sql` ou `.py` coerente com o repo)
      Verify: rodar o script 2x contra um banco com dados v6 de exemplo; conferir relatorio de somas iguais e
      idempotencia (segunda execucao nao duplica). NAO alterar `database/database.sql`.

## Pontos de atencao (nao sao itens, sao riscos a vigiar)
- REGRA DURA: nunca introduzir o caractere de porcentagem em `database/database.sql` (nem comentario). Nao editar o arquivo.
- Colunas geradas (`fee_segment`, `microcredit_eligible`, `exposure_customer_id`): `FetchedValue()`, nunca gravar; `refresh` apos INSERT para ler.
- `account.customer_id` perdeu o UNIQUE: tirar `unique=True` do model E tratar `customer.account` como LISTA em todo lugar.
- Nome da constraint UNIQUE de `document`: inline -> `customer_document_key` (autogerado); se nao casar, detectar por IntegrityError.
- `fee`: coluna e `customer_segment` (nao `customer_type`); valor derivado de `customer.fee_segment` (EI/MEI = INDIVIDUAL).
- Validacao de schema (400) acontece ANTES de qualquer query — manter as regras condicionais no JSON, nao no controller.
- Escopo: SO o titular v7. NAO implementar microcredito (Etapa 2), jobs nem fatura/encargo (Etapa 3). D5/D6 ja decididos.
- NAO push/PR/rebase/merge; NAO remover worktree; NAO recriar branch.

## Verificacao executada (para o revisor ler sem reexecutar)
- Stack: `docker compose up` (api+db) na worktree. Portas 5432/3000 estavam
  ocupadas por OUTRA worktree (etapa-0); subi esta em API_PORT=3100 / DB_PORT=5532
  via `.env` (gitignored). O schema v7 nasceu do `database/database.sql` VERBATIM.
- venv criada na worktree a partir de `requirements-dev.txt` (+ `tzdata` para o
  zoneinfo no Windows; sem ele a coleta do test_transfer_ted.py quebra na importacao).
- Suite completa (com os env vars de porta/host apontando para o stack):
  `python -m pytest tests -q` -> **138 passed, 2 skipped** (os 2 skips sao a janela
  STR da TED, esperado). Inclui 6 testes novos das rotas v7 (contas adicionais +
  vinculos) e o 409 por documento duplicado.
- `import app` OK a partir de src/ (41+ rotas registradas, error_verification sem
  codigo repetido).
- Migracao v6->v7: harness de self-test (banco hibrido v6+v7, 1 MEI com conta/saldo/
  ledger/chave CPF) rodado 2x -> conservacao de dinheiro OK (saldo e ledger iguais
  antes/depois), idempotencia OK (PF=1, EI=1, 1 conta PF, chave CPF portada p/ a PF).
  Arquivos: database/migrations/00_staging_pf_revenue.sql, 01_v6_to_v7_titular.sql, README.md.
- SANITY CHECK do `database/database.sql`: contem 'fluxos v7' e 'customer_segment',
  NAO contem o caractere de porcentagem (o arquivo NAO foi editado).
- flake8 nos arquivos tocados: sem F-level novo (so W292/W293 pre-existentes no repo).

## Dependencias de ordem (resumo)
Models (1-3) -> erros (4) -> schema (5) -> repo/dto/controller de cliente (6-7) -> rotas novas (8) ->
pix (9) -> transfer + bug (10) -> auditoria final (11) -> testes v7 verdes (12) -> migracao (13, independente, por ultimo).
