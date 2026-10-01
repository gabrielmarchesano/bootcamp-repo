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
| Idempotência | `Idempotency-Key` obrigatório em todo POST que move dinheiro (8–64 caracteres `A-Z a-z 0-9 - _`). Ausente/malformado → 400 `QIT001015`. Mesma key + mesmo corpo (SHA-256 canônico) → **200** com a resposta original. Mesma key + corpo diferente → 409 `QIT001016` |
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

| | Método | Rota | Corpo / params | Sucesso | Erros |
|---|---|---|---|---|---|
| ✅ TEF · ⏳ PIX/TED | POST | `/transfers` | **Idempotency-Key** · `source_account_id, method, amount, destination{account_id}` | TEF: **201** `COMPLETED` (200 no replay) | 400 · 404 `QIT001009` · 409 `QIT001013` conta não ativa · 409 `QIT001016` · 422 `QIT001017` saldo · 422 `QIT001018` mesma conta · 422 `QIT001019` limite noturno |
| ✅ | GET | `/transfers/{id}` | — | 200 | 404 `QIT001020` |
| ✅ | GET | `/accounts/{id}/transfers` | `?status&limit&cursor` (origem OU destino) | 200 `items, next_cursor` | 400 · 404 |
| ✅ RECEIVED · ⏳ demais | POST | `/webhooks/spi` | `event, external_id, amount, destination_account{branch, number}, sender{name, document, ispb}` | **200 sempre** `status (CREDITED\|RETURNED)`; repetição devolve o original | 400 · 403 |
| ⏳ | POST | `/webhooks/str` | — | 200 | — |

TEF: saldo disponível precisa cobrir `amount + fee`. Origem e destino `ACTIVE`. Lançamento: `TEF_SENT −amount origem / TEF_RECEIVED +amount destino` e, se houver tarifa, `TRANSFER_FEE −fee origem / +fee FEE_REVENUE`.
PIX recebido: credita contas `ACTIVE` ou `BLOCKED`; qualquer outro caso vira `RETURNED`, sem lançamento. Lançamento: `PIX_RECEIVED −amount SPI_SETTLEMENT / +amount cliente`.
Limite noturno: 20h–6h (Brasília), soma das saídas ≤ R$ 1.000,00, exatamente no teto é permitido.
Tarifa: tabela `fee(method, customer_type)`, vigente por `effective_from`.

## D · Cartões e faturas ⏳

Sem mudança em relação ao contrato v6: emissão, autorização (HOLD/reserva), desfazimento, captura, estorno, faturas, pagamento e encargos. Chamador PROCESSOR ganha token próprio quando o sprint começar.

## Jobs ⏳

`collect_installments` · `run_scheduled_teds` · `reconcile_spi_str` · `expire_authorizations` · `close_invoices` · `run_invoice_autopay` · `mark_overdue_invoices` · `dispatch_outbox_events` (o outbox já é gravado; falta quem envie).

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

Próximo livre: `QIT001021`. Aposentados, não reutilizar: `QIT001001`, `001002`, `001004`, `001005`, `001006` (eram do `sample_entity`, removido).

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
