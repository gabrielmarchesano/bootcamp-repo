# Verificação — Etapa 0: Estabilizar a main (schema v6)

Worktree: `c:\Users\Gustavo\Desktop\RFC\bootcamp-repo\.worktrees\etapa-0-estabilizar`
Branch: `etapa-0-estabilizar`
Ambiente: Windows, Python 3.11.9, venv em `.venv/` (git-ignored), Docker 29.8.2 + Compose v5.5.1.
Decisão do usuário: Opção A — Etapa 0 estabiliza a main AINDA no schema v6; v7 só na Etapa 1.

## O que foi implementado

### Itens 0.1–0.6 (já descritos)
- **0.1** `resources/__init__.py` exporta as 10 classes de resource que `app.py` importa.
- **0.2** `models/__init__.py` com todos os enums/models (Pix, cartões, fatura).
- **0.3** `git mv pix_key_injury.py → pix_key_inquiry.py` (classe já era `PixKeyInquiry`).
- **0.4** `repositories/__init__.py` com os 6 repositórios faltantes.
- **0.5** `transfer_controller.py`: `create_pix` (KEY/MANUAL, on-us 201 / externo 202),
  `create_pix_reversal` (REVERSAL, e2e `D…`, 202), `create_ted` (imediata/agendada) e `cancel`.
  Constante `NIGHT_LIMIT`; `OutboxEvent.TRANSFER_COMPLETED` (inexistente) → `OUTGOING_TEF`;
  import de `Customer` no controller; helper `generate_str_control_number`.
  Schemas Pix/TED criados: `post_pix_transfer`, `post_pix_reversal`, `post_ted_transfer`,
  `post_webhook_str`, `get_pix_key_lookup`, `post_pix_key`.
  Lock de duas contas (origem+destino, em ordem de id) no Pix on-us para não haver deadlock em
  Pix cruzados; colisão de `end_to_end_id`/`pix_key_inquiry_id` em corrida vira 409 (uso único do e2e).
- **0.6** `incoming_transfer_repository.create` aceita e persiste `pix_transfer_type`,
  `receiver_pix_key`, `pix_message`, `original_transfer_id` (corrige o `TypeError`).

### Item 0.7 (passou a ser necessário no v6)
- `database/database.sql` revertido para a versão COMMITADA (HEAD = v6), descartando a modificação v7
  pré-aplicada, via `git checkout HEAD -- database/database.sql`.
- Correção mínima do seed de contas internas: a coluna `account.customer_id` era `UUID NOT NULL`,
  mas o `ck_account_type` exige `customer_id IS NULL` para contas INTERNAL — contradição que fazia o
  seed de contas internas (LOAN_PORTFOLIO etc.) falhar com
  `null value in column "customer_id" of relation "account" violates not-null constraint`.
  Removido o `NOT NULL` da coluna (a nulabilidade correta por tipo de conta já é garantida pelo
  `ck_account_type`), alinhando com `src/models/account.py` (que trata `customer_id` como anulável).
  Verificado: `database/database.sql` NÃO contém o caractere de porcentagem (loader psycopg2).

## Verificação executada (Docker/Postgres de pé)

- `docker compose up -d --build`: db e api `healthy`; `/health_check` → 204.
- Schema sobe do zero sem erro; `SELECT count(*) FROM account WHERE type='INTERNAL'` → 7 (seed OK).
  Confirma 0.7: o schema v6 corrigido carrega do zero via docker compose.
- `import app` a partir de `src/` → `APP OK` (sem ImportError).
- `pytest tests --collect-only` → 130 testes, 0 erros de import/coleta.
  (Instalado `tzdata` no venv: dependência do ambiente de teste no Windows, não do código-fonte.)
- `pix_key_inquiry.py` existe; `pix_key_injury.py` não existe.

## Resultado do pytest (suíte completa, `pytest tests -q`)

```
95 passed, 33 failed, 2 skipped
```

- **2 skipped:** `test_transfer_ted.py` — testes de TED imediata que só rodam DENTRO da janela do STR
  (dia útil, 6h30–17h); fora da janela são `skipif` por desenho do próprio teste.
- **95 passed:** inclui TODOS os testes de conta/cliente, TEF, Pix (chave, manual, devolução,
  concorrência), TED (agendada, cancelamento, recebida, janela), webhook SPI/STR e schema-rules.
  Ou seja, todo o escopo da Etapa 0 (0.1–0.7) está verde.
- **33 failed:** TODOS em `tests/integration/card/` (cartão, carteira de crédito, autorização,
  fatura). Causa única e idêntica em todos: faltam os SCHEMAS de request das rotas de cartão
  (`Exception: Nao encontrei o schema 'post_credit_wallet.json' em /app/schemas`), e por isso o
  `@SchemaHandler.validate(...)` estoura antes do controller → 500. Os controllers/resources/
  repositories de cartão existem e estão ligados (a app importa). Faltam estes arquivos em
  `src/schemas/`: `post_credit_wallet.json`, `patch_credit_wallet_limit.json`,
  `patch_credit_wallet_status.json`, `get_wallet_invoices.json`, `post_card.json`,
  `patch_card_activate.json`, `patch_card_status.json`, `post_card_authorization.json`,
  `post_card_authorization_increment.json`, `post_card_authorization_reversal.json`,
  `post_card_capture.json`, `post_card_refund.json`.

## Observação sobre a meta 130/130

O plano da Etapa 0 define explicitamente os schemas de cartão/crédito/fatura como FORA de escopo
("Out of scope / documented gaps"), de etapa posterior. A correção do usuário listou o que corrigir
se um teste falhasse por motivo diferente de schema×código — "imports, métodos de transfer, incoming
transfer, schemas Pix/TED" — e cartão não está nessa lista. As 33 falhas de cartão são exatamente
esse gap documentado. Com o escopo da Etapa 0 (0.1–0.7), a suíte está em 95/130; os 33 restantes
dependem de criar os schemas de cartão, trabalho de etapa posterior. Ponto levantado ao orquestrador
para decisão (criar os schemas de cartão agora, ampliando o escopo, OU manter o corte do plano).

## Estado do ambiente ao final
- Stack Docker de pé e saudável.
- `.venv/` e artefatos temporários não versionados; apenas os arquivos pretendidos foram tocados.
