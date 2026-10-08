# Progresso do backlog — conta digital + microcrédito (v7)

Status do trabalho na branch `feat/backlog-v7`. Resume **o que já foi feito** (Etapas 0 e 1) e **o que falta** (Etapas 2, 3 e 4), para o time continuar de onde paramos.

> Base: o backlog original (`Backlog de implementação — conta digital + microcrédito.pdf`) e a RFC definem 5 etapas (0 a 4). Este branch entrega as Etapas **0** e **1**, verificadas rodando a suíte com a stack Docker (Postgres + API) de pé.

---

## Resumo rápido

| Etapa | Descrição | Status |
|-------|-----------|--------|
| 0 | Estabilizar a main | ✅ **Concluída** — suíte 130/130 (128 passed + 2 skips de TED esperados) |
| 1 | Modelo de titular v7 | ✅ **Concluída** — suíte 138 passed + 2 skips; migração v6→v7 incluída |
| 2 | Microcrédito | ⬜ A fazer |
| 3 | Fatura e jobs | ⬜ A fazer |
| 4 | Erros, testes e docs | ⬜ Parcial (os códigos de erro das Etapas 0/1 já entraram) |

Suíte atual na branch: **138 passed, 2 skipped** (os 2 skips são os testes de TED imediata, que só rodam dentro da janela do STR — comportamento esperado, não é falha).

---

## ✅ Etapa 0 — Estabilizar a main (feita)

A main (commit v6) não subia e só 36/130 testes passavam. Entregue:

- **0.1** `src/resources/__init__.py` passou a exportar os 10 Resources do `app.py` (antes exportava models por engano).
- **0.2** `src/models/__init__.py` completo (Pix, cartões, fatura — todas as tabelas do schema têm model registrado).
- **0.3** Renomeado `src/models/pix_key_injury.py` → `pix_key_inquiry.py`.
- **0.4** `src/repositories/__init__.py` exporta os 6 repositórios que faltavam (PixKey, Card, CardAuthorization, CreditWallet, Invoice, Calendar).
- **0.5** `transfer_controller`: implementados `create_pix` (KEY/MANUAL, on-us/externo, lock de 2 contas em ordem, corrida de e2e → 409), `create_pix_reversal`, `create_ted` (imediata/agendada) e `cancel`.
- **0.6** `incoming_transfer_repository.create()` passou a aceitar/persistir `pix_transfer_type` e os campos de devolução (corrige o `TypeError` que derrubava a maioria dos testes).
- **0.7** Seed da conta interna: `account.customer_id` tornado anulável (o `ck_account_type` já garante a nulabilidade por tipo), para o schema carregar do zero.
- **Extra:** criados os 12 schemas JSON de request das rotas de cartão/carteira/fatura (que já tinham controller mas não tinham schema), destravando a suíte de cartão. Isso faz parte da meta 130/130 porque os cartões já estavam na main v6.

> Observação: a Etapa 0 ficou no **schema v6**. O schema v7 só entrou na Etapa 1, junto com a migração do código.

## ✅ Etapa 1 — Modelo de titular v7 (feita)

Troca o modelo central (cliente) de v6 (CPF + `type` INDIVIDUAL/MEI + cnpj opcional) para v7 (titular PF **ou** PJ, teto de microcrédito por patrimônio). Entregue:

- **1.1** `database/database.sql` trocado para o **schema v7** (titular PF/PJ, `customer_relationship`, tarifa por `customer_segment`, linha de crédito por patrimônio/`exposure_customer_id`, FKs compostas). Seed de conta interna já correto no v7.
- **1.2** `models/customer.py` migrado para `person_type` / `document` / `legal_nature` / `owner_customer_id`; `exposure_customer_id`, `fee_segment` e `microcredit_eligible` mapeados como colunas **geradas** (somente leitura via `FetchedValue`). Um titular agora tem **N contas** (`accounts` virou lista).
- **1.3** Novo model `CustomerRelationship` (sócio / administrador / procurador) registrado.
- **1.4** `post_customer.json` / `patch_customer.json` reescritos por `person_type` (validação condicional retorna 400 antes de consultar o banco).
- **1.5** Controller/repository/dto do cliente adaptados: dígito verificador de CPF/CNPJ, dono do EI tem de ser PF (QIT001050), elegibilidade por `annual_revenue`, 409 por documento duplicado.
- **1.6** 3 rotas novas: `POST`/`GET /customers/{id}/accounts` (QIT001051) e `POST /customers/{id}/relationships` (QIT001052).
- **1.7** Chaves Pix: teto por `person_type` (5 NATURAL / 20 LEGAL) e chave CPF/CNPJ igual ao documento do titular (QIT001041).
- **1.8** Tarifa por `fee_segment` em TEF/Pix/TED (consulta a tabela `fee` por `customer_segment`). Pix de PF e EI/MEI = tarifa zero; TED cobra o valor da tabela.
- **1.9** Script de migração **v6→v7** em `database/migrations/` (idempotente): cada MEI vira dois titulares — a PF (CPF) e o CNPJ (LEGAL/EI, `owner_customer_id` → PF); conta e receita ficam no CNPJ; soma de dinheiro conferida antes/depois.
- **Códigos de erro** QIT001050/051/052 criados (QIT001041 reusado) em `src/errors/custom_errors.py`.

### 🐞 Bug crítico corrigido nesta etapa

`TransferController._pix_manual_fields` ainda lia atributos v6 do cliente (`holder.cpf`/`cnpj`/`type`, `Customer.MEI`) num caminho de **Pix** — daria erro 500 no v7. Corrigido para `holder.document` e feita auditoria de todo o `src/`: nenhum resquício v6 restante.

### Decisões aplicadas (premissas da RFC)

- **D5** (renda da PF na migração): a renda vem **informada pela IF antes da migração** — tratada como dado de entrada (staging); o script aborta se faltar, em vez de assumir zero.
- **D6** (chave Pix CPF na conta do MEI): **portada** para a conta PF aberta na migração (não excluída).

---

## ⬜ O que falta

### Etapa 2 — Microcrédito (7 rotas)
As tabelas já existem no schema v7; falta a lógica. Itens 2.1 a 2.7: models (`CreditLine`, `Loan`, `Installment`, `LoanPayment`, `PaymentAllocation`...), repositórios com a ordem de lock conta → linha do patrimônio → contrato → parcela, rotas de credit-line (PUT/GET), simulação e contratação de empréstimo (com desembolso e TAC no ledger), listagem, e pagamento (antecipação a valor presente, CDC art. 52 §2º). **Ponto crítico:** concorrência do teto de R$ 21 mil por patrimônio (dois pedidos simultâneos, um pela conta da PF e outro pela do MEI, não podem somar mais que o teto).

**Decisões em aberto que travam a Etapa 2 (precisam de resposta do time/Jurídico):**
- **D1** — o teto de R$ 21 mil conta só o principal em aberto (premissa RFC) ou principal + juros/encargos vencidos? Trava 2.5 e 2.7.
- **D2** — sócio PF e a LTDA dele somam no mesmo teto? Premissa RFC: **não** (cada patrimônio tem o seu). Trava 2.3 e 2.5.

### Etapa 3 — Fatura e jobs
- **3.1–3.3** Model `InvoicePayment`, rota de pagamento de fatura (QIT001060/064) e rota de encargo REVOLVING/INSTALLMENT_PLAN (QIT001061). **D3** em aberto (base dos 100% do teto do rotativo).
- **3.4–3.12** Os **8 jobs** agendados (`expire_authorizations`, `close_invoices`, `mark_overdue_invoices`, `run_invoice_autopay`, `run_scheduled_teds`, `reconcile_spi_str`, `collect_installments`, `dispatch_outbox_events`), cada um como comando idempotente `python -m jobs.<nome>`.

### Etapa 4 — Erros, testes e docs
- **4.1** Faltam os códigos de erro QIT001053 a QIT001065 (os de microcrédito/fatura). Os desta faixa que as Etapas 0/1 usavam já entraram (QIT001041/050/051/052).
- **4.2–4.7** Testes de concorrência (teto de microcrédito, pagamento antecipado), do contrato (idempotência, MPO, TAC, CET, cronograma), do titular v7, de fatura/jobs, e da migração v6→v7.
- **4.8** Atualizar `docs/api-contract.md`, `docs/como-o-projeto-e-organizado.md` e o `README`.

---

## Como rodar / verificar

```bash
# sobe Postgres + API (o db builda database/database.sql)
docker compose up --build

# em outra aba, com o venv do projeto:
pip install -r requirements-dev.txt
pytest tests -q
```

Esperado nesta branch: `138 passed, 2 skipped`. Os 2 skips são a TED imediata, que só roda na janela do STR (6h30–17h em dia útil).

> `database/database.sql` **não pode conter o caractere de porcentagem** — o loader (psycopg2) o trata como marcador de parâmetro. Qualquer edição no SQL precisa respeitar isso.
