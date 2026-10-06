# Contrato de API — Conta digital + microcrédito (fluxos v6)

Fonte da verdade das rotas do time. Quando o código e este arquivo
discordarem, um dos dois está errado — conserte no mesmo PR.

Stack e camadas: as do projeto base (`docs/como-o-projeto-e-organizado.md`).
Identificadores em inglês; descrições em pt-BR. Termos regulatórios
mantidos: CPF, CNPJ, MEI, PIX, TED, TEF, SPI, STR, ISPB, KYC, PEP.

Legenda: ✅ implementado e testado · ⏳ próximo sprint

---

## Convenções transversais

| Tema | Regra |
|---|---|
| Autenticação | Header `INTERNAL-TOKEN` em todas as rotas (padrão do projeto base). Sem ele: 403 `QIT000002` |
| Rastreio | `X-Request-ID` em toda resposta (middleware do projeto base) |
| Formato do erro | `{"title", "description", "translation", "code"}` — o envelope do projeto base |
| Validação | Formato errado (JSON Schema): **400** `QIT000001`. Valor impossível ou regra de negócio: **422**. Conflito com o estado atual: **409** |
| Idempotência | `Idempotency-Key` obrigatório em todo POST que move dinheiro, no formato **UUID v4** (como o `request_control_key` da QI). Ausente/malformado → 400 `QIT001015`. A resposta ecoa o valor em `request_control_key`. Mesma key + mesmo corpo (SHA-256 canônico) → **200** com a resposta original. Mesma key + corpo diferente → 409 `QIT001016` |
| Dinheiro | Inteiro em **centavos** (`150000` = R$ 1.500,00). Float é recusado pelo schema. Taxas em fração (`0.035`) |
| Documentos | Só dígitos: CPF 11, CNPJ 14. Dígito verificador conferido (422 se não bater) |
| Datas | ISO-8601 com fuso (`2026-09-30T23:18:09-03:00`) |
| Paginação | Keyset: `?limit=1..100&cursor=<opaco>` → `next_cursor` (`null` na última página). Cursor adulterado → 400 `QIT000010` |
| Concorrência | Contas travadas sempre em ordem crescente de id (`AccountRepository.lock_customer_accounts`). Deadlock/serialização (`40P01`/`40001`) → retry automático com backoff, máx. 3 (`utils/db_retry.py`) |
| Ledger | Partidas dobradas, imutável. O banco recusa UPDATE/DELETE e operação que não soma zero |

---

## A · Clientes e contas

| | Método | Rota | Corpo / params | Sucesso | Erros |
|---|---|---|---|---|---|
| ✅ | POST | `/customers` | `cpf, name, birth_date, type (INDIVIDUAL\|MEI), cnpj (obrigatório se MEI, proibido se INDIVIDUAL), annual_revenue, is_pep?` | 201 `customer_id, account_id, branch, account_number, status, status_reason, microcredit_eligible` | 400 · 422 `QIT001003` CPF · 422 `QIT001011` CNPJ · 422 `QIT001007` data · 409 `QIT001010` |
| ✅ | GET | `/customers/{id}` | — | 200 cliente | 404 `QIT001008` |
| ✅ | PATCH | `/customers/{id}` | `annual_revenue` | 200 cliente com `microcredit_eligible` recalculado | 400 · 404 |
| ✅ | GET | `/accounts/{id}` | — | 200 `status, status_reason, balance, held_balance, available_balance, microcredit_eligible` | 404 `QIT001009` |
| ✅ | PATCH | `/accounts/{id}/status` | `status (ACTIVE\|REJECTED\|BLOCKED\|CLOSED), reason` | 200 conta | 404 · 409 `QIT001012` transição · 409 `QIT001014` encerramento |
| ✅ | GET | `/accounts/{id}/statement` | `?limit&cursor` | 200 `items[entry_id, type, method, amount, balance_after, reference_type, reference_id, external_id, created_at], balance, held_balance, available_balance, next_cursor` | 400 · 404 |

**Status inicial** (ordem de avaliação): KYC reprovado → `REJECTED/KYC_REJECTED` · idade < 18 → `REJECTED/UNDERAGE` · PEP → `PENDING/PEP_REVIEW` · idade ≥ 80 → `PENDING/SENIOR_REVIEW` · demais → `ACTIVE`. Todos respondem **201**: a tentativa fica registrada (trilha de PLD).

**Transições**: `PENDING → ACTIVE|REJECTED` · `ACTIVE ↔ BLOCKED` · `ACTIVE|BLOCKED → CLOSED`. `REJECTED` e `CLOSED` são finais. Encerrar exige `balance = 0`, `held_balance = 0` e nenhum loan `ACTIVE`.

**Elegibilidade**: `annual_revenue ≤ 36000000` (R$ 360 mil). Mesmo teto no CHECK `ck_eligibility` do banco.

## B · Microcrédito ⏳

| | Método | Rota | Corpo / params | Sucesso | Erros |
|---|---|---|---|---|---|
| ⏳ | PUT | `/accounts/{id}/credit-line` | `total_limit, monthly_interest_rate, origination_fee_rate` | 200 linha (nova `version`) | 404 · 409 conta não ativa · 422 inelegível · 422 fora da regra MPO |
| ⏳ | GET | `/accounts/{id}/credit-line` | — | 200 | 404 |
| ⏳ | POST | `/accounts/{id}/loans/simulation` | `amount, installment_count` | 200 `origination_fee_amount, net_amount, effective_cost_monthly, effective_cost_annual, installments[]` | 404 · 422 |
| ⏳ | POST | `/accounts/{id}/loans` | **Idempotency-Key** · `amount, installment_count (2–24), purpose, sfn_debt_declaration=true` | 201 `loan_id, net_amount, CET, installments[]` | 400 · 404 · 409 · 422 |
| ⏳ | GET | `/accounts/{id}/loans` | `?status&limit&cursor` | 200 | 404 |
| ⏳ | GET | `/loans/{id}` | — | 200 loan + installments | 404 |
| ⏳ | POST | `/loans/{id}/payments` | **Idempotency-Key** · `amount, mode (REDUCE_TERM\|REDUCE_INSTALLMENT)` | 201 | 400 · 404 · 409 · 422 |

Guardrails MPO (Res. CMN 4.854/2020): taxa ≤ 4% a.m. · TAC ≤ 3%, proporcional abaixo de 120 dias · saldo de microcrédito + amount ≤ R$ 21.000 · prazo 60–720 dias. Já estão como CHECK no banco.

## C · Transferências

Pix e TED seguem o padrão da API da QI Tech (docs.qitech.com.br), **sem integrar**: rotas por trilho aninhadas na conta, `pix_transfer_type`, `target_account` com dígito e tipo de conta, consulta ao DICT antes do Pix por chave, devolução de Pix recebido, 201 para o que já liquidou e 202 para o que espera o trilho. A tabela `transfer` é uma só para os três meios.

| | Método | Rota | Corpo / params | Sucesso | Erros |
|---|---|---|---|---|---|
| ✅ | POST | `/transfers` | **Idempotency-Key** · `source_account_id, method (TEF), amount, destination{account_id}` | **201** `COMPLETED` (200 no replay) | 400 · 404 `QIT001009` · 409 `QIT001013` · 409 `QIT001016` · 422 `QIT001017` · 422 `QIT001018` · 422 `QIT001019` |
| ✅ | GET | `/transfers/{id}` | — | 200 | 404 `QIT001020` |
| ✅ | GET | `/accounts/{id}/transfers` | `?status&limit&cursor` (origem OU destino) | 200 `items, next_cursor` | 400 · 404 |
| ✅ | PATCH | `/transfers/{id}/cancel` | — | 200 `CANCELED` | 404 · 409 `QIT001028` (só `SCHEDULED`) |
| ✅ | POST | `/accounts/{id}/pix_keys` | `key_type (CPF\|CNPJ\|EMAIL\|PHONE\|EVP), key_value?` (EVP é gerada pela API) | 201 | 404 · 409 `QIT001013` · 409 `QIT001029` já registrada · 409 `QIT001040` teto (PF 5, MEI 20) · 422 `QIT001041` CPF/CNPJ de outro titular |
| ✅ | GET · DELETE | `/accounts/{id}/pix_keys` · `/accounts/{id}/pix_keys/{pix_key_id}` | — | 200 | 404 |
| ✅ | GET | `/pix_keys/{chave}` | `?account_id` (quem consulta) | 200 `end_to_end_id, ispb, account_*, owner_name, owner_masked_document, owner_person_type, on_us, expires_at` | 400 · 404 `QIT001021` |
| ✅ | POST | `/accounts/{id}/pix_transfers` | **Idempotency-Key** · `pix_transfer_type`. `KEY`: `pix_key, end_to_end_id, amount, pix_message?`. `MANUAL`: `target_account{ispb, branch, number, digit?, document, name, account_type}, amount, pix_message?` | on-us **201** `COMPLETED` · externo **202** `SENT` · 200 replay | 404 `QIT001036` consulta de outra conta · 409 `QIT001022` e2e já usado · 422 `QIT001023` consulta expirada · `QIT001024` emoji · `QIT001037` chave ≠ consulta · `QIT001042` destino inválido · `QIT001017` · `QIT001019` |
| ✅ | POST | `/accounts/{id}/incoming_transfers/{incoming_id}/reversals` | **Idempotency-Key** · `amount, reversal_reason (CLIENT_REQUEST\|RECONCILIATION), pix_message?` | **202** `SENT` (id começa com `D`) | 404 `QIT001038` · 409 `QIT001013` · 422 `QIT001026` soma > recebido · `QIT001027` > 90 dias · `QIT001039` não devolvível |
| ✅ | POST | `/accounts/{id}/ted_transfers` | **Idempotency-Key** · `target_account{…}, amount, schedule_date?` | **202** `SENT` ou `SCHEDULED` | 422 `QIT001025` fora da janela sem data · `QIT001049` data inválida · `QIT001042` TED para esta IF |
| ✅ | POST | `/webhooks/spi` | `event`: `RECEIVED` (`external_id, amount, destination_account, sender, pix_transfer_type?, receiver_pix_key?, pix_message?, original_end_to_end_id` se `REVERSAL`) · `SETTLED` (`end_to_end_id`) · `REJECTED` (`end_to_end_id, error_code, error_description?`) | **200 sempre** | 400 · 403 |
| ✅ | POST | `/webhooks/str` | `event`: `RECEIVED` (como o SPI) · `SETTLED` · `RETURNED` (`str_control_number, reason?`) | **200 sempre** | 400 · 403 |

**Regras que o banco garante** (testadas em `tests/integration/database`): o `end_to_end_id` do Pix por chave tem de vir de uma consulta da **mesma conta** (FK composta) e vale para **uma** transferência (UNIQUE); formato BCB `E|D + ISPB + yyyyMMddHHmm + 11`; devolução sempre com entrada original e motivo.

**Lançamentos.** Pix externo: `PIX_SENT −amount cliente / +amount SPI_SETTLEMENT`. Pix on-us: `PIX_SENT / PIX_RECEIVED` entre as contas. Devolução: `PIX_REVERSAL_SENT` e `PIX_REVERSAL_RECEIVED`. TED: `TED_SENT` contra `STR_SETTLEMENT`. Pix rejeitado devolve valor e tarifa (`REVERSAL`). TED devolvida devolve só o valor: a TED foi executada.

**Decisões do time.** TED fora da janela (dia útil, 6h30–17h) com `schedule_date` ausente recebe 422 — a API não reagenda sozinha (QI `TED000011`). Agendada não debita na criação: saldo e limite são conferidos na execução. Consulta ao DICT vale 15 min (premissa: a QI não publica). Devolução não conta no limite noturno. DICT de chaves externas é um mock (`src/utils/dict_mock.py`: `fornecedor@externo.com`, `+5511988887777`).

## D · Cartões e faturas

A **carteira de crédito** (`credit_wallet`, o "wallet" da QI) tem o limite, o ciclo e os encargos. Os cartões (virtual, físico, reemissão) são instrumentos que consomem o MESMO limite e caem na MESMA fatura. Cartão só de débito não tem carteira e debita a conta.

| | Método | Rota | Corpo / params | Sucesso | Erros |
|---|---|---|---|---|---|
| ✅ | POST | `/accounts/{id}/credit_wallets` | `total_limit, closing_day, due_day (1–28), monthly_interest_rate, fine_rate (≤ 0.02), autopay?` | 201 `ACTIVE` | 404 · 409 `QIT001013` · 409 `QIT001030` já existe carteira viva |
| ✅ | GET | `/credit_wallets/{id}` | — | 200 com `available_limit` e `status_events` | 404 `QIT001044` |
| ✅ | PATCH | `/credit_wallets/{id}/limit` | `total_limit` | 200 | 422 `QIT001031` abaixo do usado |
| ✅ | PATCH | `/credit_wallets/{id}/status` | `status (ACTIVE\|BLOCKED\|CLOSED), reason` | 200 | 409 `QIT001032` (fechar exige `used_limit = 0`) |
| ✅ | GET | `/credit_wallets/{id}/invoices` · `/invoices/{id}` | `?status` | 200 (detalhe com itens) | 404 `QIT001048` |
| ✅ | POST | `/accounts/{id}/cards` | `type (VIRTUAL\|PLASTIC), functions (DEBIT\|CREDIT\|MULTIPLE), printed_name, card_name?, brand?, contactless_enabled?` (só físico) | 201: virtual `ACTIVE`, físico `EMBOSSING` (+ `activation_code` fora de produção) | 409 `QIT001013` · 422 `QIT001045` crédito sem carteira ativa |
| ✅ | GET | `/accounts/{id}/cards` · `/cards/{id}` | — | 200 com `status_events` (a QI expõe o mesmo) | 404 `QIT001043` |
| ✅ | PATCH | `/cards/{id}/activate` | `code` (6 dígitos) | 200 `ACTIVE` | 409 `QIT001032` · 422 `QIT001033` código · 422 `QIT001034` não é físico |
| ✅ | PATCH | `/cards/{id}/status` | `status (ACTIVE\|BLOCKED\|CANCELED\|LOST\|STOLEN\|FRAUD), reason` | 200 | 409 `QIT001032` |
| ✅ | POST | `/cards/authorizations` | `authorization_id, card_id, function, amount, installment_count? (só crédito), merchant_name?, mcc?` | **200 sempre** `APPROVED` (`00`) ou `DECLINED` + `denial_reason` (`51` saldo/limite · `62` cartão · `57` conta/carteira/função · `14` cartão inexistente) | 400 · 403 |
| ✅ | GET | `/cards/authorizations/{authorization_id}` | — | 200 com `events` | 404 `QIT001046` |
| ✅ | POST | `/cards/authorizations/{authorization_id}/increments` | `request_id, amount` | 200 com `decision` | 404 · 409 `QIT001047` |
| ✅ | POST | `/cards/authorizations/{authorization_id}/reversals` | `request_id, amount?` (sem amount = total) | 200 | 400 · 404 · 409 `QIT001047` |
| ✅ | POST | `/cards/captures` · `/cards/refunds` | `capture_id\|refund_id, authorization_id, amount` | 200 (idempotente pelo id da rede) | 404 · 409 `QIT001047` · 422 `QIT001035` estorno > captura |

**Transições.** Cartão: `EMBOSSING → ACTIVE` só pelo código; `EMBOSSING → CANCELED|LOST|STOLEN`; `ACTIVE ↔ BLOCKED`; `ACTIVE|BLOCKED → CANCELED|LOST|STOLEN|FRAUD`. Terminais: `CANCELED, LOST, STOLEN, FRAUD`. Carteira: `ACTIVE ↔ BLOCKED`, `ACTIVE|BLOCKED → CLOSED`.

**Dinheiro da autorização** (`card_authorization_event`, enumerador da QI 1 para 1). `AUTHORIZATION`/`INCREMENTAL_AUTHORIZATION` criam HOLD (débito, `held_balance`) ou reserva (crédito, `used_limit`). `REVERSAL`/`PARTIAL_REVERSAL` soltam. A primeira `CAPTURE` troca o HOLD pelo valor capturado (pode ser maior ou menor): débito lança `DEBIT_PURCHASE` contra `CARD_SETTLEMENT`; crédito lança as parcelas nas faturas. `REFUND`/`PARTIAL_REFUND` são eventos: a autorização segue `CAPTURED` (o "completed" da QI). `REFUNDED` fica no enumerador, mas deixou de ser destino.

**Faturas.** Compra antes do dia de fechamento cai na fatura que fecha neste mês; no dia ou depois, na do mês seguinte. Vencimento: o primeiro `due_day` depois do fechamento, ajustado a dia útil. Parcela *k* cai *k−1* meses depois; faturas de meses seguintes nascem `FUTURE` (id 6) e viram `OPEN` quando a anterior fechar. Compra no crédito não gera lançamento no ledger: até o pagamento, o registro é a fatura.

## Jobs ⏳

`collect_installments` · `run_scheduled_teds` (SCHEDULED → SENT\|FAILED) · `reconcile_spi_str` · `expire_authorizations` (APPROVED → EXPIRED + evento `EXPIRATION`) · `close_invoices` (OPEN → CLOSED e FUTURE → OPEN) · `run_invoice_autopay` · `mark_overdue_invoices` · `dispatch_outbox_events`. O outbox já grava `type` no padrão de `webhook_type` da QI (`baas.pix_transfer.outgoing_pix`, `baas.card.status_change`…); o job embrulha em `{webhook_type, webhook_datetime, data}`.

Ainda não construídos no sprint 4: pagamento de fatura (`POST /invoices/{id}/payments`) e encargos do rotativo (`POST /invoices/{id}/charges`).

---

## Códigos de erro do domínio

| Código | HTTP | Nome no contrato v6 | Quando |
|---|---|---|---|
| `QIT001003` | 422 | — | CPF com dígito verificador errado (herdado do projeto base) |
| `QIT001007` | 422 | — | data que não existe no calendário (herdado do projeto base) |
| `QIT001008` | 404 | — | cliente não encontrado |
| `QIT001009` | 404 | — | conta não encontrada (inclui conta interna e id que não é UUID) |
| `QIT001010` | 409 | `CUSTOMER_ALREADY_EXISTS` | CPF ou CNPJ já cadastrado |
| `QIT001011` | 422 | — | CNPJ com dígito verificador errado |
| `QIT001012` | 409 | `INVALID_STATUS_TRANSITION` | transição fora da máquina de estados |
| `QIT001013` | 409 | `ACCOUNT_NOT_ACTIVE` | origem ou destino não está ACTIVE |
| `QIT001014` | 409 | — | encerramento com saldo, bloqueio ou loan ativo |
| `QIT001015` | 400 | `IDEMPOTENCY_KEY_REQUIRED` | header ausente ou malformado |
| `QIT001016` | 409 | `IDEMPOTENCY_CONFLICT` | mesma key, corpo diferente |
| `QIT001017` | 422 | `INSUFFICIENT_BALANCE` | saldo disponível < valor + tarifa |
| `QIT001018` | 422 | `SAME_ACCOUNT` | origem = destino |
| `QIT001019` | 422 | `NIGHT_LIMIT_EXCEEDED` | teto noturno estourado |
| `QIT001020` | 404 | — | transferência não encontrada |
| `QIT001021` | 404 | QI `PIX000017` | chave Pix não encontrada no DICT |
| `QIT001022` | 409 | QI `PXT000061` | `end_to_end_id` já usado |
| `QIT001023` | 422 | — | consulta ao DICT expirada |
| `QIT001024` | 422 | QI `PXT000048` | emoji na `pix_message` |
| `QIT001025` | 422 | QI `TED000011` | TED fora da janela sem `schedule_date` |
| `QIT001026` | 422 | QI `PXT000017` | devoluções acima do recebido |
| `QIT001027` | 422 | QI `PXT000015` | devolução depois de 90 dias |
| `QIT001028` | 409 | QI `PSC000028` | cancelar transferência que não está `SCHEDULED` |
| `QIT001029` | 409 | — | chave Pix já registrada |
| `QIT001030` | 409 | QI `CIN000043` | carteira viva já existe |
| `QIT001031` | 422 | QI `CIN000110` | novo limite abaixo do usado |
| `QIT001032` | 409 | QI `CARD000013` | transição inválida de cartão ou carteira |
| `QIT001033` | 422 | QI `CARD000020` | código de ativação inválido |
| `QIT001034` | 422 | QI `CARD000023` | operação só para cartão físico |
| `QIT001035` | 422 | — | estorno acima do capturado |
| `QIT001036` | 404 | QI `PIX000056` | consulta ao DICT não encontrada para esta conta |
| `QIT001037` | 422 | QI `PXT000128` | chave enviada ≠ chave da consulta |
| `QIT001038` | 404 | — | entrada não encontrada (ou de outra conta) |
| `QIT001039` | 422 | — | entrada não devolvível (STR, devolvida, ou já é devolução) |
| `QIT001040` | 409 | Regulamento Pix | teto de chaves (PF 5, PJ 20) |
| `QIT001041` | 422 | — | chave CPF/CNPJ de outro titular |
| `QIT001042` | 422 | QI `PXT000132`/`PXT000141` | conta de destino inválida |
| `QIT001043` | 404 | QI `CARD000011` | cartão não encontrado |
| `QIT001044` | 404 | QI `CIN000007` | carteira não encontrada |
| `QIT001045` | 422 | — | cartão com crédito sem carteira ativa |
| `QIT001046` | 404 | — | autorização não encontrada |
| `QIT001047` | 409 | — | operação não aceita no status da autorização |
| `QIT001048` | 404 | — | fatura não encontrada |
| `QIT001049` | 422 | QI `PSC000008` | `schedule_date` não é dia útil futuro |

Próximo livre: `QIT001050`. Aposentados, não reutilizar: `QIT001001`, `001002`, `001004`, `001005`, `001006` (eram do `sample_entity`, removido).

---

## Onde o código diverge do contrato v6 (e por quê)

| v6 dizia | Ficou | Motivo |
|---|---|---|
| `X-API-Key` por chamador · HMAC nos webhooks | `INTERNAL-TOKEN` | Padrão do projeto base: um token só para todas as rotas internas. HMAC volta quando houver trilho fora da nossa rede |
| `{"error": {"code": "INSUFFICIENT_BALANCE"}}` | Envelope `QIT0…` do projeto base | Um formato só na API inteira; a tabela acima faz a ponte |
| Validação 422 | 400 formato · 422 valor | Semântica do projeto base (README, seção 7) |
| Ledger `TED_FEE` | `TRANSFER_FEE` + coluna `method` | Tarifa existe em TEF também; o meio já está na linha |
| Tarifa TEF R$ 0 | **R$ 1,00 (premissa)** | O bootcamp exige tarifa na transferência; com zero, o requisito não aparece na demo. PIX segue gratuito |
| Resposta do POST /customers | + `branch`, `account_number`, `status_reason` | É o endereço que o SPI usa para creditar PIX |
| Item do extrato | + `entry_id`, `reference_type`, `reference_id` | Liga cada linha à transferência que a gerou |
| `Idempotency-Key` livre (8–64) | UUID v4 | Mesmo formato do `request_control_key` da QI; todo cliente já gera UUID v4 |
| `POST /transfers` para TEF, PIX e TED | Rotas por trilho para Pix e TED | Padrão da QI (`/account/{key}/pix_transfer`, `/account/{key}/ted`). A tabela segue única |
| Limite e fatura no cartão | Carteira de crédito (`credit_wallet`) | Padrão da QI (wallet): um limite e uma fatura para todos os cartões do cliente |
| `card_capture` e `card_refund` | `card_authorization_event` | Enumerador de eventos da QI; ganha incremental, reversão parcial e expiração |
| Tipos do outbox `TRANSFER_COMPLETED`… | `baas.<recurso>.<evento>` | É o `webhook_type` da QI |