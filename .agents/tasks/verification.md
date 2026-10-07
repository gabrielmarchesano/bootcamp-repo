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

## Schemas de cartão/carteira/fatura (escopo ampliado — decisão Opção B)

Os cartões já fazem parte da main v6 que a Etapa 0 estabiliza; o item 0.8 pede 130/130, e os 33 testes
de cartão estão na suíte. As rotas de cartão (controllers/resources/repositories) JÁ existiam no código,
só faltavam os SCHEMAS de request. Criados os 12 por engenharia reversa dos contratos que os controllers
já consomem, no mesmo estilo dos schemas existentes:
- `post_credit_wallet.json` (total_limit, closing_day/due_day 1–28, monthly_interest_rate >= 0,
  fine_rate 0–0.02 — espelha os CHECKs da tabela credit_wallet; `autopay` opcional).
- `patch_credit_wallet_limit.json` (total_limit).
- `patch_credit_wallet_status.json` (status ACTIVE/BLOCKED/CLOSED + reason).
- `get_wallet_invoices.json` (query param `status` repetível, enum dos status de fatura).
- `post_card.json` (oneOf por type: VIRTUAL sem contactless, PLASTIC com contactless_enabled —
  por isso VIRTUAL+contactless e 400).
- `patch_card_activate.json` (code, 6 dígitos).
- `patch_card_status.json` (status + reason).
- `post_card_authorization.json` (authorization_id, card_id, function DEBIT/CREDIT, amount,
  installment_count 1–24, merchant_name?, mcc?; parcelamento >= 2 só com function CREDIT → DEBIT
  parcelado e 400).
- `post_card_authorization_increment.json` (request_id, amount).
- `post_card_authorization_reversal.json` (request_id; amount opcional — reversão total omite amount).
- `post_card_capture.json` (capture_id, authorization_id, amount).
- `post_card_refund.json` (refund_id, authorization_id, amount).

NÃO foi tocado microcrédito/jobs/encargo de fatura; só os schemas de request das rotas de cartão já
existentes. `database.sql` continua v6 com o fix do seed, sem alterações adicionais.

## Resultado FINAL do pytest (suíte completa, `pytest tests -q`)

```
128 passed, 2 skipped in ~26s
```

Ou seja **130/130** com os 2 skips esperados.

- **2 skipped (esperado, não e falha):** `tests/integration/transfer/test_transfer_ted.py:39` e `:57` —
  os dois testes de TED IMEDIATA, gated pelo próprio `skipif(not ted_window_open())` do teste
  (só rodam em dia útil, 6h30–17h, horário de Brasília). O próprio backlog/decisão prevê esses 2 skips.
- **128 passed:** TODO o escopo — conta/cliente, TEF, Pix (chave/manual/devolução/concorrência),
  TED (agendada/cancelamento/recebida/janela), webhook SPI/STR, schema-rules E as 33 de cartão
  (emissão, ativação, status, autorização/decisão, incremental, reversão, captura, estorno,
  faturas/parcelas, concorrência).

## Estado do ambiente ao final
- Stack Docker de pé e saudável.
- `.venv/` e artefatos temporários não versionados; apenas os arquivos pretendidos foram tocados.
