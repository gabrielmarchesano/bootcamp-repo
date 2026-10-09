# RFC — Infra de conta digital + microcrédito (base service)

Oct 8, 2026 · @Raff

Infraestrutura de conta digital com microcrédito para uma instituição financeira (IF) de microcrédito, construída sobre o base service do bootcamp: cadastro, conta, transação com controle de saldo, tarifa na transferência e extrato paginado. Cada CPF e cada CNPJ é um titular com várias contas, e o teto do microcrédito vale por patrimônio.

| Campo | Valor |
| --- | --- |
| Time | Time do bootcamp-repo (base service + microcrédito) |
| Data | 08/10/2026 |
| Versão | 3.3 (esquema v7 com `id` BIGINT + `key` UUID e tipos `enum_*`; rotas do `src/app.py` atual, com microcrédito, fatura e jobs; fluxos v8) |
| Stack | Python + FastAPI + PostgreSQL + Docker, sobre o bootcamp-base-api |

**O que mudou da 3.2 para a 3.3.** Microcrédito, pagamento e encargo de fatura e os 8 jobs saíram do desenho e estão no `src/app.py` (51 rotas, com `POST /job/{job_name}`), com testes black box. As marcas de *previsto* e a lista de divergências de 08/10 saíram: tudo o que ela listava foi corrigido.

**O que mudou da 3.1 para a 3.2.** As rotas passaram para o singular e com `{*_key}` no caminho, como estão no `src/app.py` (`/customer/{customer_key}/account`, `/card/authorization`, …). O `database/database.sql` trocou a PK UUID por `id BIGINT` interno + `key UUID` público e os `TEXT + CHECK` por tipos `enum_*` nativos. Microcrédito, pagamento e encargo de fatura e os jobs continuam no desenho, mas ainda não estão no `app.py`: aparecem marcados como **previstos**. Os códigos de erro e as respostas foram conferidos contra `src/errors` e os DTOs.

## Contextualização

### Entendendo o problema

Somos a infraestrutura tecnológica de uma única IF (single-tenant) que atende classes média/baixa, microempreendedores e microempresas. A IF decide o crédito — limite e taxa da linha de microcrédito, TAC e limite da carteira de crédito — e nos informa via API; nós executamos contas, transferências, cartões, desembolso, cobrança, pagamentos e extrato. Quem chama o serviço são os sistemas da IF, identificados por um token interno; os trilhos de pagamento (SPI, STR) e a processadora de cartão chamam os webhooks.

Na vida real, a mesma pessoa tem uma conta como pessoa física e outras para cada CNPJ dela. Por isso o cliente do sistema é o **titular**: um CPF ou um CNPJ, cada um com várias contas. O titular é também quem assina o microcrédito, o tomador da Res. CMN 4.854/2020.

O serviço precisa sustentar cinco garantias:

- **O mesmo real não é gasto duas vezes:** um débito só é aprovado com a conta travada, mesmo com várias requisições disputando o mesmo saldo. Se falhar, a conta fica negativa e a IF absorve o prejuízo.
- **O dinheiro se conserva:** todo lançamento é em partidas dobradas e imutável; cada operação soma zero e o extrato reconstrói o saldo. Se falhar, o saldo deixa de bater com o extrato e com a conciliação do SPI, do STR e da bandeira.
- **Pedido repetido não move dinheiro de novo:** a mesma `Idempotency-Key` com o mesmo corpo devolve a resposta original; o mesmo `external_id` de webhook credita uma vez só; na rede de cartão, o id da rede (`authorization_id`, `request_id`, `capture_id`, `refund_id`) faz o mesmo papel. Se falhar, um clique duplo ou um reenvio por timeout vira débito duplo.
- **Microcrédito dentro da regra MPO** (Res. CMN 4.854/2020): taxa ≤ 4% a.m., TAC ≤ 3% (proporcional abaixo de 120 dias), prazo de 60 a 720 dias, saldo do tomador ≤ R$ 21 mil na mesma instituição e declaração de dívida no SFN ≤ R$ 80 mil. O teto de R$ 21 mil soma a pessoa física e o EI/MEI dela, que respondem com o mesmo patrimônio; sociedade (LTDA, SLU) tem teto próprio. Se falhar, a IF opera fora da regra do produto.
- **Elegibilidade por renda ou receita bruta:** PF, MEI e microempresa com até R$ 360 mil por ano contratam microcrédito — o teto da microempresa, não o do MEI. Acima disso, o titular abre conta e usa transferências e cartões.

Dependências externas, todas mockadas nesta entrega: DICT e SPI (PIX), STR (TED), processadora e bandeira (cartões) e um serviço de KYC/PLD. Nenhuma delas é chamada com linha travada no banco.

Fora do escopo: cálculo de limite, score, taxa e política de crédito (decisão da IF); multa, mora e renegociação; chargeback; tokenização de cartão; KYC e PEP dos sócios de PJ (o KYC da PJ olha só o CNPJ); depósito em espécie — o dinheiro entra só pelos webhooks do SPI e do STR.

### Explicando a solução de forma macro

O coração do serviço é um ledger em partidas dobradas (`ledger_entry`) que nenhuma rota consegue editar: o banco recusa `UPDATE` e `DELETE` por trigger e recusa, no `COMMIT`, qualquer operação cujas pernas não somem zero. Em volta dele ficam quatro domínios, e os estados de todos eles moram em tabelas próprias:

| Domínio | Tabelas | Papel |
| --- | --- | --- |
| Titular e conta | `customer`, `customer_relationship`, `account`, `fee`, `holiday` | Titular PF ou PJ (um CPF ou um CNPJ), sócios e procuradores da PJ, várias contas por titular, tarifa por segmento e calendário bancário |
| Microcrédito | `credit_line`, `credit_line_version`, `loan`, `installment`, `loan_payment`, `payment_allocation` | Linha do patrimônio definida pela IF, contrato com tomador e patrimônio, cronograma Price, cobrança e antecipação |
| Pix e transferências | `pix_key`, `pix_key_inquiry`, `transfer`, `incoming_transfer` | Chaves Pix, consulta ao DICT, TEF, Pix e TED de saída, devolução de Pix, Pix e TED recebidos |
| Cartões | `credit_wallet`, `card`, `card_authorization`, `card_authorization_event`, `invoice`, `invoice_item`, `invoice_payment` | Carteira de crédito com um limite e uma fatura para todos os cartões, autorização (HOLD ou reserva), captura, estorno e fatura |
| Estados (todos os domínios) | 12 enumeradoras `*_status` e 9 históricos `*_status_event` | Estado que não está na tabela o banco recusa; toda troca de status vira um evento append-only |

A conta de cliente guarda o saldo materializado (`balance`) e a soma dos HOLDs de débito (`held_balance`); disponível = `balance − held_balance`. As contas internas (`LOAN_PORTFOLIO`, `ORIGINATION_FEE_REVENUE`, `INTEREST_REVENUE`, `FEE_REVENUE`, `SPI_SETTLEMENT`, `STR_SETTLEMENT`, `CARD_SETTLEMENT`) são a contrapartida de cada lançamento; o saldo delas é a soma do ledger. Cada fato que a IF precisa saber grava um evento em `outbox_event` na mesma transação, já com o `type` no formato `webhook_type` da QI (`baas.account.opened`, `baas.account.status_change`, `baas.tef.outgoing_tef`, `baas.pix_transfer.outgoing_pix`, `baas.pix_transfer.incoming_pix`, `baas.ted.outgoing_ted`, `baas.ted.incoming_ted`, `baas.pix_key.status_change`, `baas.credit_wallet.status_change`, `baas.card.status_change`, `baas.card.authorization`).

**Titular, patrimônio e tomador.** Cada CPF e cada CNPJ é um `customer` (`person_type` `NATURAL` ou `LEGAL`) com várias contas. O empresário individual e o MEI apontam para a pessoa natural dona (`owner_customer_id`), porque não têm patrimônio separado dela; sociedade (`SLU`, `LTDA`) tem patrimônio próprio, e sócios e procuradores ficam em `customer_relationship`. O banco calcula três colunas: `exposure_customer_id` (o patrimônio que responde pela dívida), `fee_segment` (`INDIVIDUAL` para PF e EI/MEI, `BUSINESS` para sociedade) e `microcredit_eligible` (renda ou receita ≤ R$ 360 mil). A linha de microcrédito é do patrimônio, e o contrato guarda o tomador, a conta e o patrimônio, amarrados por três FKs compostas.

Cada requisição é uma transação, confirmada pelo controller só no fim. A concorrência é segurada por três regras:

1. **Ordem global de lock:** `account` (por id crescente) → `credit_line` → `loan` → `installment`; nos cartões, `account` → `credit_wallet` → `card_authorization` (a fatura não é travada à parte: quem grava nela já segura a carteira; o PATCH de cartão trava `account` → `card`); `transfer` depois das contas. Deadlock ou falha de serialização (`40P01`, `40001`) repete a transação inteira, até 3 vezes, com backoff exponencial (`utils/db_retry.retry_on_deadlock`, aplicado nos controllers de conta, transferência, webhook, chave Pix, carteira, cartão e autorização).
2. **Saldo lido só depois do `SELECT … FOR UPDATE`**, e a idempotência conferida antes e de novo depois do lock.
3. **Chamada externa fora da transação:** DICT, SPI, STR e KYC nunca são chamados com linha travada.

Convenções:

- Dinheiro em centavos (`BIGINT`); taxas como fração (`0.035` = 3,5% a.m.); documentos só com dígitos; `TIMESTAMPTZ` com regras em `America/Sao_Paulo`; identificadores em inglês.
- **Identidade:** toda entidade de domínio tem `id BIGINT GENERATED ALWAYS AS IDENTITY` (PK e alvo das FKs, nunca sai do banco) e `key UUID` (o identificador público). A API recebe a `key` no caminho (`{customer_key}`, `{account_key}`, …) e a devolve nos campos `*_id` das respostas (`customer_id`, `account_id`, …). Id que não é UUID responde o `404` da entidade, não `400`.
- **Tipos:** valores fixos de coluna (`person_type`, `legal_nature`, `method`, `key_type`, tipo de lançamento, …) são tipos `enum_*` nativos do PostgreSQL; status mora em tabela enumeradora (o código lê pelo `enumerator`, nunca pelo id), e toda troca de status grava `*_status_event` e `outbox_event` na mesma transação.

Alternativas descartadas:

- **Um cliente por CPF, com `type` `INDIVIDUAL` ou `MEI` e um `cnpj` opcional:** não comporta várias empresas por pessoa nem a microempresa até R$ 360 mil, e mistura o teto do CPF com o do CNPJ.
- **Linha de crédito por conta:** a PF e o MEI dela, em contas diferentes, teriam dois tetos de R$ 21 mil sobre o mesmo patrimônio.
- **Tomador como o par CPF + CNPJ opcional:** toda consulta de limite precisaria ramificar; com um id por titular, o vocabulário `NATURAL`/`LEGAL` é o mesmo do DICT.
- **Limite e fatura no cartão:** o virtual, o físico e a reemissão teriam limites separados; a carteira de crédito dá um limite e uma fatura para todos.
- **Ler o saldo e depois travar:** duas requisições leem R$ 100, as duas aprovam R$ 80 e a conta fecha em −R$ 60.
- **Travar as contas na ordem do pedido:** A→B e B→A simultâneas seguram uma conta cada e entram em deadlock.
- **Conferir a idempotência só antes do lock:** no clique duplo, as duas requisições passam pela checagem antes de qualquer uma gravar.
- **Ledger de uma perna só:** não concilia contra SPI, STR e bandeira, e não prova que o dinheiro se conserva.
- **Travar as contas internas:** `FEE_REVENUE` entra em quase toda operação e viraria uma fila única para o banco inteiro.
- **Extrato paginado por offset:** um Pix que entra entre a página 1 e a 2 repete a última linha; o keyset não sofre com isso.
- **Dinheiro em float:** é como um sistema financeiro começa a perder centavos; o schema recusa.
- **UUID como PK de tudo:** índice e FK maiores e inserção espalhada pelo índice; o `id BIGINT` fica para o banco e a `key UUID` para quem chama, sem expor sequência.
- **Modelo de risco próprio:** o cálculo do limite é da IF; nós aplicamos só os guardrails regulatórios.
- **Isolamento por instituição (`instituicao_id`):** o banco é single-tenant.
- **Responder 4xx a webhook e à decisão da rede de cartão:** o trilho reenviaria a mensagem em loop; webhook e autorização (inclusive a incremental) respondem `200` com o desfecho no corpo. Captura, reversão e estorno chegam depois da decisão e podem responder `4xx`.

## Implementação

### Rotas

O `src/app.py` registra **51 rotas**, todas no padrão singular com `{*_key}`: as de titular e conta, microcrédito, transferências, cartões e faturas, e `POST /job/{job_name}`, que dispara um dos 8 jobs.

Regras que valem para todas as rotas:

- Todas, menos `/` e `/health_check` (e qualquer `OPTIONS`), exigem o cabeçalho `INTERNAL-TOKEN`; sem ele ou com valor errado, `403 QIT000002`.
- Corpo ou query fora do JSON Schema: `400 QIT000001` (os schemas são fechados: campo a mais também é `400`). Parâmetro inválido (cursor adulterado, formato de chave Pix, valor acima do autorizado na reversão): `400 QIT000010`. Valor impossível ou regra de negócio: `422`. Conflito com o estado atual: `409`. Rota inexistente `404 QIT000404`, verbo errado `405 QIT000405`, erro inesperado `500 QIT000500`.
- Corpo de erro: `{title, description, translation, code}`.
- Todo POST que move dinheiro pela conta exige `Idempotency-Key` em UUID v4: mesma chave e mesmo corpo (SHA-256 canônico) devolvem `200` com a resposta original; mesma chave e corpo diferente, `409 QIT001016`; chave ausente ou malformada, `400 QIT001015`. O schema roda antes: corpo inválido sem chave responde `QIT000001`. Na rede de cartão a idempotência é pelo id da rede.
- Transferência responde `201` quando liquidou (`COMPLETED`), `202` quando vai pelo trilho ou foi agendada (`SENT`, `SCHEDULED`) e `200` na repetição.

**Operacional**

| Método | Caminho | O que faz | Entrada | Saídas |
| --- | --- | --- | --- | --- |
| GET | `/` | Diz qual serviço é este. Aberta, sem token | — | `200` `{service, id}` |
| GET | `/health_check` | Diz se o serviço está de pé, sem consultar o banco. Aberta, sem token | — | `204` |

**A · Titulares e contas**

| Método | Caminho | O que faz | Entrada | Saídas |
| --- | --- | --- | --- | --- |
| POST | `/customer` | Cadastra o titular (um CPF ou um CNPJ) e abre a primeira conta na mesma transação. KYC reprovado ou PF menor de 18 também responde `201`, com a conta `REJECTED` (`KYC_REJECTED`, `UNDERAGE`); PEP ou PF com 80+ abre `PENDING` (`PEP_REVIEW`, `SENIOR_REVIEW`); o resto, `ACTIVE` | `person_type` (`NATURAL` \| `LEGAL`), `document` (CPF 11 ou CNPJ 14 dígitos), `name`, `annual_revenue` (centavos), `birth_date` (só e obrigatório em NATURAL), `legal_nature` (`EI` \| `SLU` \| `LTDA`, só e obrigatório em LEGAL), `owner_customer_id` (só e obrigatório em EI: a PF dona), `is_pep`? (só NATURAL) | `201` com `customer_id`, `account_id`, `branch`, `account_number`, `status`, `status_reason`, `microcredit_eligible`; `400 QIT000001`; `422 QIT001003` CPF, `QIT001011` CNPJ, `QIT001007` data, `QIT001050` dono do EI inexistente ou que não é PF; `409 QIT001010` documento já cadastrado |
| GET | `/customer/{customer_key}` | Devolve o titular | — | `200` com `customer_id`, `person_type`, `document`, `name`, `birth_date`, `legal_nature`, `owner_customer_id`, `annual_revenue`, `revenue_reference_date`, `microcredit_eligible`, `kyc_status`, `is_pep`, `account_id` (a conta mais antiga), `created_at`; `404 QIT001008` |
| PATCH | `/customer/{customer_key}` | Atualiza a renda ou receita; o banco recalcula `microcredit_eligible`. Contrato vigente segue até quitar | `annual_revenue` | `200` com o titular; `400 QIT000001`; `404 QIT001008` |
| POST | `/customer/{customer_key}/account` | Abre mais uma conta do titular, já `ACTIVE` | — | `201` com `account_id`, `customer_id`, `branch`, `account_number`, `status`, `status_reason`, `created_at`; `404 QIT001008`; `422 QIT001051` KYC do titular não aprovado |
| GET | `/customer/{customer_key}/account` | Lista as contas do titular, da mais antiga para a mais nova, sem paginação | — | `200` com `items`; `404 QIT001008` |
| POST | `/customer/{customer_key}/relationship` | Liga um sócio, administrador ou procurador (PF) à PJ do caminho | `natural_customer_id`, `role` (`PARTNER` \| `ADMINISTRATOR` \| `ATTORNEY`) | `201` com `legal_customer_id`, `natural_customer_id`, `role`, `created_at`; `404 QIT001008` (qualquer das pontas); `422 QIT001052` vínculo que não é PJ → PF ou já existente |
| GET | `/account/{account_key}` | Devolve a conta com os saldos e o histórico de status | — | `200` com `account_id`, `customer_id`, `branch`, `account_number`, `status`, `status_reason`, `status_events`, `balance`, `held_balance`, `available_balance`, `microcredit_eligible`, `created_at`; `404 QIT001009`, também para conta interna |
| PATCH | `/account/{account_key}/status` | Muda o status pela máquina de estados, com a conta travada: `PENDING → ACTIVE \| REJECTED`, `ACTIVE → BLOCKED \| CLOSED`, `BLOCKED → ACTIVE \| CLOSED`; `REJECTED` e `CLOSED` são finais. Cada troca grava `account_status_event` | `status` (`ACTIVE` \| `REJECTED` \| `BLOCKED` \| `CLOSED`), `reason` | `200` com a conta; `400 QIT000001`; `404 QIT001009`; `409 QIT001012` transição inválida, `QIT001014` encerrar com saldo, HOLD ou contrato ativo |
| GET | `/account/{account_key}/statement` | Extrato do mais novo ao mais antigo, por keyset. Compra no crédito fica na fatura; HOLD aparece só em `held_balance` | `limit` (1 a 100, padrão 10), `cursor` (opaco) | `200` com `account_id`, `balance`, `held_balance`, `available_balance`, `items` (`entry_id`, `type`, `method`, `amount`, `balance_after`, `reference_type`, `reference_id`, `external_id`, `created_at`) e `next_cursor`; `400 QIT000001`, `QIT000010` cursor adulterado; `404 QIT001009` |

**B · Microcrédito**

| Método | Caminho | O que faz | Entrada | Saídas |
| --- | --- | --- | --- | --- |
| PUT | `/customer/{customer_key}/credit_line` | A IF informa a linha do patrimônio; o titular tem de ser a raiz (a PF ou a sociedade). Grava nova `version` e `available_limit = total_limit − saldo de microcrédito do patrimônio`. Mesmo corpo, mesmo estado | `total_limit`, `monthly_interest_rate`, `origination_fee_rate` | `200` com a linha; `400 QIT000001`; `404 QIT001008`; `422 QIT001053` EI/MEI usa a linha do dono, `QIT001055` fora da regra MPO |
| GET | `/customer/{customer_key}/credit_line` | Devolve a linha do patrimônio; para EI/MEI, a do dono | — | `200`; `404 QIT001008` titular, `QIT001065` sem linha |
| POST | `/account/{account_key}/loan/simulation` | Simula o contrato sem gravar | `amount`, `installment_count` | `200` com `origination_fee_amount`, `net_amount`, CET a.m. e a.a., `installments`; `404 QIT001009`; `422 QIT001054` inelegível, `QIT001056` sem linha |
| POST | `/account/{account_key}/loan` | Contrata e desembolsa na mesma transação. O tomador é o titular da conta; limite e teto de R$ 21 mil são do patrimônio | `Idempotency-Key`; `amount`, `installment_count` (2 a 24, a cada 30 dias), `purpose`, `sfn_debt_declaration = true` | `201` com `loan_id`, `net_amount`, CET e cronograma; `200` repetição; `400 QIT001015`; `404 QIT001009`; `409 QIT001013`, `QIT001016`; `422 QIT001054` inelegível, `QIT001056` sem linha, `QIT001057` limite insuficiente, `QIT001058` acima de R$ 21 mil no patrimônio |
| GET | `/account/{account_key}/loan` | Lista os contratos da conta | `status`, `limit`, `cursor` | `200`; `404 QIT001009` |
| GET | `/loan/{loan_key}` | Devolve o contrato com tomador, patrimônio e parcelas | — | `200`; `404 QIT001062` |
| POST | `/loan/{loan_key}/payment` | Pagamento avulso ou antecipado, da parcela mais antiga à mais nova, com desconto a valor presente (CDC art. 52 §2º). Devolve à linha do patrimônio só o principal | `Idempotency-Key`; `amount`, `mode` (`REDUCE_TERM` \| `REDUCE_INSTALLMENT`) | `201`; `200` repetição; `400 QIT001015`; `404 QIT001062`; `409 QIT001063` contrato quitado, `QIT001016`; `422 QIT001059` acima do devido, `QIT001017` saldo |

**C · Transferências**

Tarifa vigente por `fee_segment` (tabela `fee`, premissa do time): TEF R$ 1,00, Pix R$ 0,00, TED R$ 10,00, iguais para `INDIVIDUAL` e `BUSINESS`. Limite noturno: R$ 1.000 somando as saídas da conta das 20h às 6h (horário de Brasília); a tarifa não entra na soma.

| Método | Caminho | O que faz | Entrada | Saídas |
| --- | --- | --- | --- | --- |
| POST | `/transfer` | TEF entre contas da IF: trava as duas contas em ordem de id, exige as duas `ACTIVE`, aplica tarifa e limite noturno e liquida na hora | `Idempotency-Key`; `source_account_id`, `method` (`TEF`), `amount`, `destination.account_id` | `201 COMPLETED`; `200` repetição; `400 QIT001015`; `404 QIT001009`; `409 QIT001013`, `QIT001016`; `422 QIT001017` saldo, `QIT001018` mesma conta, `QIT001019` limite noturno |
| GET | `/transfer/{transfer_key}` | Devolve a transferência | — | `200` com `transfer_id`, `request_control_key` (a `Idempotency-Key`), `method`, `status`, `amount`, `fee`, `source_account_id`, `on_us`, `destination`, `created_at`, `completed_at` e, conforme o meio, os blocos `pix`, `ted` e `failure`; `404 QIT001020` |
| GET | `/account/{account_key}/transfer` | Lista as transferências em que a conta é origem ou destino, por keyset | `status` (repetível: `?status=SENT&status=COMPLETED`), `limit` (1 a 100, padrão 10), `cursor` | `200` com `items` e `next_cursor`; `400 QIT000001`, `QIT000010` cursor; `404 QIT001009` |
| PATCH | `/transfer/{transfer_key}/cancel` | Cancela a TED agendada | — | `200 CANCELED`; `404 QIT001020`; `409 QIT001028` se não está `SCHEDULED` |
| POST | `/account/{account_key}/pix_key` | Registra chave Pix na conta `ACTIVE`. Teto por conta: 5 para `NATURAL`, 20 para `LEGAL`; chave CPF ou CNPJ tem de ser o documento do titular; EVP é gerada pela API | `key_type` (`CPF` \| `CNPJ` \| `EMAIL` \| `PHONE` \| `EVP`), `key_value`? (obrigatório, menos em EVP) | `201` com `pix_key_id`, `account_id`, `key_type`, `key_value`, `status`, `created_at`; `400 QIT000010` valor ausente ou fora do formato do tipo; `404 QIT001009`; `409 QIT001013`, `QIT001029` já registrada, `QIT001040` teto; `422 QIT001041` documento de outro titular |
| GET | `/account/{account_key}/pix_key` | Lista as chaves `ACTIVE` da conta | — | `200` com `items`; `404 QIT001009` |
| DELETE | `/account/{account_id}/pix_keys/{pix_key_key}` | Apaga a chave (soft delete: vira `DELETED` e pode ser registrada de novo em outra conta). O caminho está assim no `app.py`, fora do padrão das demais rotas | — | `200` com a chave e `status = DELETED`; `404 QIT001009` conta, `QIT001021` chave inexistente, de outra conta ou já apagada |
| GET | `/pix_key/{pix_key}` | Consulta ao DICT: grava `pix_key_inquiry` e devolve o `end_to_end_id` que o Pix por chave tem de usar (vale 15 min, só para a conta que consultou) | `account_id` na query (a `key` da conta que consulta) | `200` com `pix_key`, `key_type`, `end_to_end_id`, `ispb`, `account_branch`, `account_number`, `account_digit`, `account_type`, `owner_name`, `owner_masked_document`, `owner_person_type`, `on_us`, `expires_at`; `400 QIT000001` sem `account_id`, `QIT000010` chave fora de formato; `404 QIT001009` conta, `QIT001021` chave |
| POST | `/account/{account_key}/pix_transfer` | Pix por chave (`KEY`) ou por dados da conta (`MANUAL`). On-us liquida na hora; externo debita contra `SPI_SETTLEMENT` e vai ao SPI | `Idempotency-Key`; `pix_transfer_type`; `KEY`: `pix_key`, `end_to_end_id`; `MANUAL`: `target_account` (`ispb`, `branch`, `number`, `digit`?, `document`, `name`, `account_type`); `amount`, `pix_message`? (até 140) | on-us `201 COMPLETED`; externo `202 SENT`; `200` repetição; `400 QIT001015`; `404 QIT001009`, `QIT001036` consulta não é desta conta; `409 QIT001013`, `QIT001016`, `QIT001022` e2e já usado; `422 QIT001017`, `QIT001019`, `QIT001023` consulta expirada, `QIT001024` emoji, `QIT001037` chave diferente da consulta, `QIT001042` documento não bate com o titular da conta de destino |
| POST | `/account/{account_key}/incoming_transfer/{incoming_transfer_key}/reversal` | Devolve um Pix recebido, total ou parcial, sempre pelo SPI e sem tarifa | `Idempotency-Key`; `amount`, `reversal_reason` (`CLIENT_REQUEST` \| `RECONCILIATION`) | `202 SENT` (e2e começa com `D`); `200` repetição; `400 QIT001015`; `404 QIT001009`, `QIT001038` entrada inexistente ou de outra conta; `409 QIT001013`, `QIT001016`; `422 QIT001026` soma acima do recebido, `QIT001039` entrada não `CREDITED` |
| POST | `/account/{account_key}/ted_transfer` | TED para outra instituição: na janela (dia útil, 6h30–17h) debita contra `STR_SETTLEMENT` e vai ao STR; com `schedule_date` fica `SCHEDULED`, sem débito e sem tarifa | `Idempotency-Key`; `target_account` (mesmo formato do Pix `MANUAL`), `amount`, `schedule_date`? (`AAAA-MM-DD`) | `202 SENT` ou `SCHEDULED`; `200` repetição; `400 QIT001015`; `404 QIT001009`; `409 QIT001013`, `QIT001016`; `422 QIT001017`, `QIT001019`, `QIT001025` fora da janela sem data, `QIT001042` TED para esta IF, `QIT001049` data que não é dia útil futuro |
| POST | `/webhook/spi` | Pix recebido (`RECEIVED`) e retorno do Pix enviado (`SETTLED`, `REJECTED`). Credita conta `ACTIVE` ou `BLOCKED`; outro caso vira `RETURNED`. Devolução (`REVERSAL`) só credita se apontar para um Pix nosso `COMPLETED` daquela conta, sem passar do valor original. `REJECTED` devolve valor e tarifa. Idempotente por `(rail, external_id)` | `event`; `RECEIVED`: `external_id`, `amount`, `destination_account` (`branch`, `number`), `sender` (`name`, `document`, `ispb`), `pix_transfer_type`?, `original_end_to_end_id` (se `REVERSAL`), `receiver_pix_key`?, `pix_message`?; `SETTLED`: `end_to_end_id`; `REJECTED`: `end_to_end_id`, `error_code`, `error_description`? | `200` sempre: a entrada (`incoming_transfer_id`, `rail`, `pix_transfer_type`, `external_id`, `status`, `amount`, `original_transfer_id`), a transferência atualizada ou `{result: IGNORED}`; `400 QIT000001`; `403` |
| POST | `/webhook/str` | TED recebida (`RECEIVED`) e retorno da TED enviada (`SETTLED`, `RETURNED`). `RETURNED` devolve só o valor | `event`; `RECEIVED`: mesmos campos do SPI; `SETTLED` e `RETURNED`: `str_control_number`, `reason`? | `200` sempre; `400 QIT000001`; `403` |

**D · Cartões e faturas** — a carteira de crédito (`credit_wallet`) tem o limite, o ciclo e os encargos; os cartões consomem o mesmo limite e caem na mesma fatura. Nenhuma rota de cartão usa `Idempotency-Key`.

| Método | Caminho | O que faz | Entrada | Saídas |
| --- | --- | --- | --- | --- |
| POST | `/account/{account_key}/credit_wallet` | A IF abre a carteira de crédito da conta `ACTIVE`; nasce `ACTIVE` com `used_limit = 0` | `total_limit`, `closing_day`, `due_day` (1 a 28), `monthly_interest_rate`, `fine_rate` (≤ 2%), `autopay`? | `201` com `wallet_id`, `account_id`, `status`, `status_events`, `total_limit`, `used_limit`, `available_limit`, `closing_day`, `due_day`, `monthly_interest_rate`, `fine_rate`, `autopay`, `created_at`; `404 QIT001009`; `409 QIT001013`, `QIT001030` já existe carteira viva |
| GET | `/credit_wallet/{wallet_key}` | Devolve a carteira | — | `200`; `404 QIT001044` |
| PATCH | `/credit_wallet/{wallet_key}/limit` | A IF muda o limite | `total_limit` | `200`; `404 QIT001044`; `422 QIT001031` abaixo do usado |
| PATCH | `/credit_wallet/{wallet_key}/status` | `ACTIVE ↔ BLOCKED`, `ACTIVE \| BLOCKED → CLOSED`; `CLOSED` é final | `status` (`ACTIVE` \| `BLOCKED` \| `CLOSED`), `reason` | `200`; `404 QIT001044`; `409 QIT001032` transição inválida ou fechar com `used_limit ≠ 0` |
| GET | `/credit_wallet/{wallet_key}/invoice` | Lista as faturas da carteira, da mais nova para a mais antiga, sem itens | `status`? (repetível: `OPEN`, `CLOSED`, `PARTIALLY_PAID`, `PAID`, `OVERDUE`, `FUTURE`) | `200` com `items` (`invoice_id`, `wallet_id`, `reference_month`, `status`, `closing_date`, `due_date`, `total_amount`, `paid_amount`); `404 QIT001044` |
| GET | `/invoice/{invoice_key}` | Devolve a fatura com os itens | — | `200` com `items` (`invoice_item_id`, `type`, `amount`, `installment_number`, `installment_total`, `description`); `404 QIT001048` |
| POST | `/account/{account_key}/card` | Emite cartão na conta `ACTIVE`: virtual nasce `ACTIVE`; físico nasce `EMBOSSING`, com código de ativação de 6 dígitos (só o hash fica no banco; fora de produção o código volta na resposta) | `type` (`VIRTUAL` \| `PLASTIC`), `functions` (`DEBIT` \| `CREDIT` \| `MULTIPLE`), `printed_name` (até 26), `card_name`? (até 15), `brand`? (padrão `VISA`), `contactless_enabled`? (só físico, padrão `true`) | `201` com `card_id`, `account_id`, `wallet_id`, `type`, `functions`, `brand`, `last4`, `card_name`, `printed_name`, `contactless_enabled`, `status`, `status_events`, `created_at` (+ `activation_code` fora de produção); `404 QIT001009`; `409 QIT001013`; `422 QIT001045` crédito sem carteira `ACTIVE` |
| GET | `/account/{account_key}/card` | Lista os cartões da conta | — | `200` com `items`; `404 QIT001009` |
| GET | `/card/{card_key}` | Devolve o cartão | — | `200`; `404 QIT001043` |
| PATCH | `/card/{card_key}/activate` | Ativa o cartão físico `EMBOSSING` com o código | `code` (6 dígitos) | `200 ACTIVE`; `404 QIT001043`; `409 QIT001032` não está `EMBOSSING`; `422 QIT001033` código, `QIT001034` não é físico |
| PATCH | `/card/{card_key}/status` | `EMBOSSING → CANCELED \| LOST \| STOLEN`; `ACTIVE → BLOCKED \| CANCELED \| LOST \| STOLEN \| FRAUD`; `BLOCKED → ACTIVE` ou os mesmos finais. `CANCELED`, `LOST`, `STOLEN` e `FRAUD` são finais; `EMBOSSING → ACTIVE` só pelo `/activate` | `status` (`ACTIVE` \| `BLOCKED` \| `CANCELED` \| `LOST` \| `STOLEN` \| `FRAUD`), `reason` | `200`; `404 QIT001043`; `409 QIT001032` |
| POST | `/card/authorization` | Autoriza: débito cria HOLD na conta; crédito reserva limite da carteira. Aprovada vale 7 dias (`expires_at`). Idempotente por `authorization_id` | `authorization_id`, `card_id`, `function` (`DEBIT` \| `CREDIT`), `amount`, `installment_count`? (1 a 24; acima de 1 só crédito), `merchant_name`?, `mcc`? | `200` sempre com `authorization_id`, `status` (`APPROVED` \| `DECLINED`), `response_code`, `approval_code`, `denial_reason`, `authorized_amount`. Recusa, na ordem: `FUNCTION_NOT_SUPPORTED` `57`, `CARD_NOT_ACTIVE` `62`, `ACCOUNT_NOT_ACTIVE` `57`, `WALLET_NOT_ACTIVE` `57`, `INSUFFICIENT_LIMIT` `51`, `INSUFFICIENT_FUNDS` `51`; cartão inexistente `INVALID_CARD` `14` (não grava linha). Aprovada: `00` |
| GET | `/card/authorization/{authorization_key}` | Devolve a autorização com os eventos. A chave do caminho é o `authorization_id` da rede | — | `200` com `authorization_id`, `card_id`, `function`, `status`, `response_code`, `approval_code`, `denial_reason`, `amount`, `authorized_amount`, `captured_amount`, `refunded_amount`, `installment_count`, `events`; `404 QIT001046` |
| POST | `/card/authorization/{authorization_key}/increment` | Autorização incremental: mais HOLD ou reserva na mesma autorização `APPROVED`, com as mesmas regras de recusa. Idempotente por `request_id` | `request_id`, `amount` | `200` com a autorização e `decision`, `decision_response_code`, `decision_denial_reason`; `404 QIT001046`; `409 QIT001047` se não está `APPROVED` |
| POST | `/card/authorization/{authorization_key}/reversal` | Desfazimento total (`REVERSED`) ou parcial (segue `APPROVED`): solta HOLD ou reserva. Idempotente por `request_id` | `request_id`, `amount`? (padrão: todo o autorizado) | `200`; `400 QIT000010` acima do autorizado; `404 QIT001046`; `409 QIT001047` se não está `APPROVED` |
| POST | `/card/captures` | Captura (pode haver várias; o valor não é limitado ao autorizado). Débito solta o HOLD e lança `DEBIT_PURCHASE` contra `CARD_SETTLEMENT` (pode negativar a conta); crédito troca a reserva pelo valor e lança as parcelas nas faturas. Idempotente por `capture_id` | `capture_id`, `authorization_id`, `amount` | `200` com a autorização `CAPTURED`; `404 QIT001046`; `409 QIT001047` se não está `APPROVED` ou `CAPTURED` |
| POST | `/card/refunds` | Estorno como evento (`REFUND` ou `PARTIAL_REFUND`); a autorização segue `CAPTURED`. Débito lança `PURCHASE_REFUND`; crédito devolve limite e lança item negativo na fatura do ciclo. Idempotente por `refund_id` | `refund_id`, `authorization_id`, `amount` | `200`; `404 QIT001046`; `409 QIT001047` se não está `CAPTURED`; `422 QIT001035` estorno acima do capturado |
| POST | `/invoice/{invoice_key}/payment` | Paga a fatura, total ou parcial, e devolve o limite da carteira | `Idempotency-Key`; `amount` | `201` com `status` (`PAID` \| `PARTIALLY_PAID`) e `remaining_amount`; `200` repetição; `400 QIT001015`; `404 QIT001048`; `409 QIT001064` fatura paga, `QIT001016`; `422 QIT001060` acima da fatura, `QIT001017` saldo |
| POST | `/invoice/{invoice_key}/charge` | Lança encargo definido pela IF na fatura `OVERDUE`, com o teto do rotativo (Lei 14.690/2023) | `Idempotency-Key`; `type` (`REVOLVING` \| `INSTALLMENT_PLAN`), `amount` | `201` com a fatura e o encargo; `200` repetição; `400 QIT001015`; `404 QIT001048`; `409 QIT001066` fatura não está `OVERDUE`, `QIT001016`; `422 QIT001061` acima do teto do rotativo |

**Jobs agendados** — `POST /job/{job_name}` (`200` com `processed` e `outcomes`; job inexistente, `404 QIT000404`) ou `cd src && python -m jobs.<nome>`. O agendamento é da IF. Todos são idempotentes.

| Job | O que faz |
| --- | --- |
| `collect_installments` | Diário: debita parcelas `OPEN`, `PARTIAL` e `OVERDUE` vencidas, travando conta → linha do patrimônio → contrato → parcela; sem saldo, marca `OVERDUE`, avisa a IF e tenta de novo no dia seguinte |
| `run_scheduled_teds` | Executa a TED `SCHEDULED` no dia, voltando ao início do fluxo: `SENT` ou `FAILED` |
| `reconcile_spi_str` | Consulta SPI e STR para toda transferência `SENT` sem retorno; nunca assume sucesso nem falha por timeout |
| `expire_authorizations` | `APPROVED` → `EXPIRED` + evento `EXPIRATION`: libera HOLD e reserva não capturados até `expires_at` (7 dias) |
| `close_invoices` | `OPEN` → `CLOSED` no dia de corte, com total e vencimento em dia útil; a fatura `FUTURE` do mês seguinte vira `OPEN` |
| `run_invoice_autopay` | Débito automático da fatura, no máximo um por fatura (`autopay` já é gravado na carteira) |
| `mark_overdue_invoices` | Marca `OVERDUE` a fatura vencida e não quitada e grava `original_debt_amount` |
| `dispatch_outbox_events` | Envia à IF os eventos `PENDING` de `outbox_event`, no formato `webhook_type` da QI (`baas.<recurso>.<evento>`) |

**Códigos de erro**

Gerais (`src/errors/base_error.py`):

| Código | HTTP | Quando |
| --- | --- | --- |
| `QIT000001` | 400 | Corpo ou query fora do JSON Schema |
| `QIT000002` | 403 | `INTERNAL-TOKEN` ausente ou errado |
| `QIT000010` | 400 | Parâmetro inválido: cursor adulterado, chave Pix fora de formato, `key_value` ausente, valor de reversão acima do autorizado |
| `QIT000404` | 404 | Rota inexistente |
| `QIT000405` | 405 | Verbo não aceito na rota |
| `QIT000500` | 500 | Erro inesperado |

Do domínio (`src/errors/custom_errors.py`). `QIT001001`, `QIT001002`, `QIT001004`, `QIT001005` e `QIT001006` são aposentados e não voltam. Próximo livre: `QIT001067`.

| Código | HTTP | Quando |
| --- | --- | --- |
| `QIT001003` | 422 | CPF com dígito verificador errado |
| `QIT001007` | 422 | Data que não existe no calendário |
| `QIT001008` | 404 | Titular não encontrado |
| `QIT001009` | 404 | Conta não encontrada, inclusive conta interna e id que não é UUID |
| `QIT001010` | 409 | CPF ou CNPJ já cadastrado |
| `QIT001011` | 422 | CNPJ com dígito verificador errado |
| `QIT001012` | 409 | Transição de status da conta fora da máquina de estados |
| `QIT001013` | 409 | Origem ou destino não está `ACTIVE` |
| `QIT001014` | 409 | Encerramento com saldo, HOLD ou contrato ativo |
| `QIT001015` | 400 | `Idempotency-Key` ausente ou malformada |
| `QIT001016` | 409 | Mesma chave, corpo diferente |
| `QIT001017` | 422 | Saldo disponível menor que valor + tarifa |
| `QIT001018` | 422 | Origem igual ao destino (TEF) |
| `QIT001019` | 422 | Limite noturno estourado |
| `QIT001020` | 404 | Transferência não encontrada |
| `QIT001021` | 404 | Chave Pix não encontrada (DICT ou na conta) |
| `QIT001022` | 409 | `end_to_end_id` já usado |
| `QIT001023` | 422 | Consulta ao DICT expirada |
| `QIT001024` | 422 | Emoji na `pix_message` |
| `QIT001025` | 422 | TED fora da janela sem `schedule_date` |
| `QIT001026` | 422 | Devoluções acima do recebido |
| `QIT001027` | 422 | Devolução depois de 90 dias |
| `QIT001028` | 409 | Cancelar transferência que não está `SCHEDULED` |
| `QIT001029` | 409 | Chave Pix já registrada |
| `QIT001030` | 409 | Carteira viva já existe |
| `QIT001031` | 422 | Novo limite da carteira abaixo do usado |
| `QIT001032` | 409 | Transição inválida de cartão ou carteira, inclusive fechar carteira com limite usado |
| `QIT001033` | 422 | Código de ativação inválido |
| `QIT001034` | 422 | Operação só para cartão físico |
| `QIT001035` | 422 | Estorno acima do capturado |
| `QIT001036` | 404 | Consulta ao DICT não encontrada para esta conta |
| `QIT001037` | 422 | Chave enviada diferente da chave da consulta |
| `QIT001038` | 404 | Entrada não encontrada, ou de outra conta |
| `QIT001039` | 422 | Entrada não devolvível (status diferente de `CREDITED`) |
| `QIT001040` | 409 | Teto de chaves Pix da conta (`NATURAL` 5, `LEGAL` 20) |
| `QIT001041` | 422 | Chave CPF ou CNPJ de outro titular |
| `QIT001042` | 422 | Conta de destino inválida (documento não bate, ou TED para esta IF) |
| `QIT001043` | 404 | Cartão não encontrado |
| `QIT001044` | 404 | Carteira não encontrada |
| `QIT001045` | 422 | Cartão com crédito sem carteira ativa |
| `QIT001046` | 404 | Autorização não encontrada |
| `QIT001047` | 409 | Operação não aceita no status da autorização |
| `QIT001048` | 404 | Fatura não encontrada |
| `QIT001049` | 422 | `schedule_date` não é dia útil futuro |
| `QIT001050` | 422 | Dono do EI/MEI inexistente ou que não é pessoa natural |
| `QIT001051` | 422 | Conta adicional para titular sem KYC aprovado |
| `QIT001052` | 422 | Vínculo que não liga uma PJ a uma PF, ou vínculo repetido |
| `QIT001053` | 422 | Linha de crédito pedida para EI/MEI, que usa a linha do dono |
| `QIT001054` | 422 | `CUSTOMER_NOT_ELIGIBLE`: tomador com renda ou receita anual acima de R$ 360 mil |
| `QIT001055` | 422 | `OUT_OF_MPO_RULE`: linha ou contrato fora da regra do MPO (juros acima de 4% a.m., TAC acima de 3%, limite acima de R$ 21 mil); o corpo traz o campo e a regra violada |
| `QIT001056` | 422 | `NO_CREDIT_LINE`: patrimônio do tomador sem linha de crédito ativa |
| `QIT001057` | 422 | `INSUFFICIENT_LIMIT`: valor acima do limite disponível da linha |
| `QIT001058` | 422 | `REGULATORY_CAP_EXCEEDED`: o saldo de microcrédito do patrimônio passaria de R$ 21 mil na IF (Res. CMN 4.854/2020) |
| `QIT001059` | 422 | `AMOUNT_ABOVE_DUE`: pagamento acima do saldo devedor do contrato |
| `QIT001060` | 422 | `AMOUNT_ABOVE_INVOICE`: pagamento acima do saldo da fatura |
| `QIT001061` | 422 | `REVOLVING_CAP_EXCEEDED`: juros e encargos acumulados passariam de 100% da dívida original (Lei 14.690/2023) |
| `QIT001062` | 404 | Contrato não encontrado |
| `QIT001063` | 409 | Contrato já quitado |
| `QIT001064` | 409 | Fatura já paga |
| `QIT001065` | 404 | Patrimônio sem linha de crédito cadastrada (consulta) |
| `QIT001066` | 409 | Encargo em fatura que não está `OVERDUE` |

### Banco de Dados (somente diagrama)

São 45 tabelas no `database/database.sql` v7: 24 de domínio e apoio, 12 enumeradoras de status (dourado, com os valores aceitos) e 9 históricos `*_status_event` (cinza), mais 24 tipos `enum_*`. Tabela de outro domínio aparece resumida. Legenda: PK, FK e UK como no template; `UK*` = parte de um `UNIQUE` composto (alvo das FKs compostas); coluna em itálico = gerada pelo banco; `?` = aceita nulo; linha tracejada = FK opcional; pé de galinha = um para muitos; traço nas duas pontas = um para um.

Identidade: as 16 entidades de domínio (`customer`, `account`, `credit_line`, `loan`, `installment`, `loan_payment`, `pix_key`, `pix_key_inquiry`, `transfer`, `incoming_transfer`, `credit_wallet`, `card`, `card_authorization`, `invoice`, `invoice_item`, `invoice_payment`) têm `id BIGINT` (PK, alvo de FK) e `key UUID UNIQUE` (público). `ledger_entry`, `outbox_event`, `card_authorization_event` e os históricos têm só `id BIGINT`; as enumeradoras, `id SMALLINT`; `holiday`, `fee`, `customer_relationship`, `credit_line_version` e `payment_allocation` têm PK natural ou composta. `outbox_event.aggregate_id` guarda a `key` UUID do agregado.

Tipos `enum_*`: método (`enum_transfer_method`, `enum_ledger_method`), pessoa e conta (`enum_person_type`, `enum_legal_nature`, `enum_customer_segment`, `enum_account_type`, `enum_relationship_role`), Pix e trilhos (`enum_pix_key_type`, `enum_pix_transfer_type`, `enum_external_account_type`, `enum_transfer_rail`, `enum_reversal_reason`), ledger (`enum_ledger_entry_type`, `enum_reference_type`), microcrédito (`enum_loan_payment_source`, `enum_loan_payment_mode`), cartões e fatura (`enum_card_type`, `enum_card_brand`, `enum_card_functions`, `enum_card_function`, `enum_card_auth_event_type`, `enum_denial_reason`, `enum_invoice_item_type`, `enum_invoice_payment_source`).

> Os diagramas abaixo foram gerados antes da troca de PK UUID por `id BIGINT` + `key UUID` e dos tipos `enum_*`; as tabelas, colunas de negócio e relações são as mesmas, mas precisam ser regerados.

**Titular, conta e ledger**

&#91;image: Titular, conta e ledger\]

**Microcrédito (linha por patrimônio)**

&#91;image: Microcrédito\]

**Chaves Pix e consulta ao DICT**

&#91;image: Chaves Pix e consulta ao DICT\]

**Transferências de saída e entradas**

&#91;image: Transferências\]

**Carteira de crédito, cartões e autorizações**

&#91;image: Carteira, cartões e autorizações\]

**Faturas**

&#91;image: Faturas\]

**Apoio: calendário bancário, tarifas e outbox** (sem FK)

&#91;image: Tabelas de apoio\]

Regras que ficam no próprio banco, além dos `CHECK` de cada coluna: `ledger_entry` recusa `UPDATE` e `DELETE` (trigger `tg_immutable_ledger`) e operação cujas pernas não somem zero (`tg_double_entry`, no `COMMIT`); enumeradoras, históricos de status, `pix_key_inquiry` e `card_authorization_event` só aceitam `INSERT` (`fn_append_only`). Do titular v7: `fk_ei_owner` garante que o dono do EI é pessoa natural; `fk_relationship_legal` e `fk_relationship_natural`, que o vínculo liga PJ → PF; `fk_credit_line_root`, que só a raiz do patrimônio tem linha; `fk_loan_account`, `fk_loan_exposure` e `fk_loan_credit_line` amarram conta, tomador, patrimônio e linha de cada contrato. Do Pix: `ux_pix_key_active`, uma chave ativa numa conta só; a FK composta `fk_transfer_inquiry` obriga o Pix por chave a usar o `end_to_end_id` da consulta da mesma conta, e o `UNIQUE` em `pix_key_inquiry_id`, uma vez só. Dos cartões: `ux_credit_wallet_live`, uma carteira viva (`ACTIVE` ou `BLOCKED`) por conta; `fk_card_wallet`, carteira da mesma conta do cartão; `ck_card_wallet`, cartão só de débito sem carteira; `ux_card_auth_event_external`, um evento por id da rede; `ux_invoice_open`, uma fatura `OPEN` por carteira; `ux_invoice_payment_autopay`, um débito automático por fatura. As views `vw_internal_account_balance` e `vw_microcredit_balance` dão a posição das contas internas e o saldo de microcrédito por patrimônio. Os seeds criam as 7 contas internas (com o evento de nascimento) e a tabela de tarifas.

### Fluxos

Os fluxos são a página `fluxo-v8` do draw.io do time, recortada por fluxo. A cor de cada caixa diz a camada em que o passo acontece (legenda no topo), na ordem da viagem da requisição. As operações de banco estão descritas em português — abre a transação, trava, grava, confirma, desfaz —; rotas, campos da API, status e códigos de erro seguem em inglês, iguais ao código. Os diagramas ainda mostram os caminhos no plural da versão anterior; o texto abaixo já usa os do `app.py`.

&#91;image: Escopo e guia de leitura do fluxo-v8\]

&#91;image: Legenda e convenções do fluxo-v8\]

#### Fluxo 1 — Cadastro do titular (PF ou PJ) + abertura de conta

&#91;image: Fluxo 1 — cadastro do titular, contas adicionais e vínculos\]

1. O schema confere os campos exigidos por `person_type`: `birth_date` só e obrigatório em `NATURAL`, `legal_nature` só e obrigatório em `LEGAL`, `owner_customer_id` só e obrigatório em `EI`, `is_pep` só em `NATURAL`. Fora do formato, `400` antes de qualquer consulta.
2. Data válida (`422 QIT001007`) e dígito verificador do CPF ou do CNPJ (`422 QIT001003` ou `QIT001011`). Se for EI/MEI, o dono tem de existir e ser pessoa natural, senão `422 QIT001050`; no banco, `fk_ei_owner` garante o mesmo.
3. Documento já cadastrado responde `409 QIT001010`; o `UNIQUE (document)` do banco resolve a corrida entre dois cadastros simultâneos.
4. O KYC roda fora da transação, e o controller define o status: KYC reprovado ou PF menor de 18 viram `REJECTED`; PEP ou PF com 80+, `PENDING`; o resto, `ACTIVE`. PJ não passa pela regra de idade. Todos respondem `201`, porque a tentativa precisa ficar registrada.
5. Titular, primeira conta, `account_status_event` e `outbox_event` (`baas.account.opened`) entram na mesma transação. O banco calcula `exposure_customer_id`, `fee_segment` e `microcredit_eligible`; a resposta `201` traz `microcredit_eligible`.
6. Mais contas para o mesmo titular: `POST /customer/{customer_key}/account`, que exige KYC aprovado e abre a conta `ACTIVE`. Sócios e procuradores de uma PJ: `POST /customer/{customer_key}/relationship`, que só aceita PJ → PF.

#### Fluxo 2 — Linha por patrimônio, contratação e desembolso

&#91;image: Fluxo 2a — linha de microcrédito do patrimônio\]

&#91;image: Fluxo 2b — contratação e desembolso\]

1. A IF informa a linha com `PUT /customer/{customer_key}/credit_line`, sempre na raiz do patrimônio: a PF, que também cobre o EI/MEI dela, ou a sociedade. O guardrail MPO recusa taxa acima de 4% a.m., TAC acima de 3% ou limite acima de R$ 21 mil.
2. O contrato é pedido pela conta (`POST /account/{account_key}/loan`): o tomador é o titular da conta, e o patrimônio é o `exposure_customer_id` dele. Tomador inelegível ou patrimônio sem linha recebe `422`.
3. `SELECT … FOR UPDATE` em `account` e depois na `credit_line` do patrimônio: um pedido da PF e outro do MEI dela, feitos em contas diferentes, disputam a mesma linha, e o segundo lê o limite já reduzido.
4. O controller confere o limite disponível e o teto de R$ 21 mil do patrimônio (`vw_microcredit_balance`), e calcula a TAC proporcional ao prazo, o cronograma Price e o CET.
5. Contrato (com tomador, conta e patrimônio), parcelas, baixa do limite e lançamentos de desembolso e TAC entram na mesma transação; falha no meio desfaz tudo, e reenviar com a mesma chave é seguro.

#### Fluxo 3 — Transferências (TEF, Pix e TED)

**3a · TEF**

&#91;image: Fluxo 3a — TEF\]

**3b · Pix: consulta ao DICT e envio**

&#91;image: Fluxo 3b — consulta ao DICT\]

&#91;image: Fluxo 3b — envio do Pix\]

**3c · TED**

&#91;image: Fluxo 3c — TED\]

&#91;image: Comparativo dos meios, máquina de estados e reconciliação\]

1. Cada trilho tem sua rota, como na API da QI; a tabela `transfer` é uma só para os três meios. A TEF fica em `POST /transfer`, entre contas da IF, e liquida na hora com `201`.
2. Idempotência antes de qualquer trava. As contas são travadas em ordem de id, a idempotência é conferida de novo e só então vêm status (`ACTIVE`), tarifa por `fee_segment` (Pix de PF e EI/MEI é gratuito, Res. BCB 19/2020), saldo disponível (saldo − HOLDs) e limite noturno.
3. Pix por chave tem dois passos: `GET /pix_key/{pix_key}?account_id=…` grava a consulta ao DICT e devolve o `end_to_end_id`; o envio (`POST /account/{account_key}/pix_transfer`) tem de usar esse e2e, da mesma conta, em até 15 minutos e uma vez só. O banco garante com FK composta e `UNIQUE`.
4. Pix on-us liquida na hora (`201`); o externo debita contra `SPI_SETTLEMENT`, fica `SENT`, vai ao SPI fora da transação e responde `202`. TED (`POST /account/{account_key}/ted_transfer`) só sai na janela (dia útil, 6h30–17h) e debita contra `STR_SETTLEMENT`; com `schedule_date` fica `SCHEDULED`, sem débito, e pode ser cancelada com `PATCH /transfer/{transfer_key}/cancel` até a execução pelo job `run_scheduled_teds`.
5. Pix rejeitado devolve valor e tarifa; TED devolvida devolve só o valor. O estorno entra na mesma transação que muda o status, e o ledger nunca recebe `UPDATE`.

**3d · Pix e TED recebidos, e devolução de Pix**

&#91;image: Fluxo 3d — Pix e TED recebidos e devolução\]

O webhook confere o token, ignora `(rail, external_id)` já processado com `200` e credita a conta destino `ACTIVE` ou `BLOCKED`; conta que não pode receber gera devolução automática (`RETURNED`). O titular devolve um Pix recebido com `POST /account/{account_key}/incoming_transfer/{incoming_transfer_key}/reversal`, total ou parcial, sem passar da soma recebida. A devolução respeita o prazo de 90 dias (`QIT001027`), confere o saldo disponível (`QIT001017`) e recusa TED e devolução de devolução (`QIT001039`).

**3e · Chaves Pix**

&#91;image: Fluxo 3e — chaves Pix da conta\]

O teto de chaves é por conta e segue o tipo do titular: 5 para `NATURAL`, 20 para `LEGAL`. Chave CPF ou CNPJ tem de ser o documento do próprio titular da conta, então a PF e o MEI dela registram cada um a sua. A conta é travada no registro, o que mantém o teto honesto com dois pedidos paralelos; a unicidade entre contas é do índice `ux_pix_key_active`.

#### Fluxo 4 — Cobrança e pagamento de parcelas

&#91;image: Fluxo 4a — cobrança automática no vencimento\]

&#91;image: Fluxo 4b — pagamento avulso ou antecipado\]

1. **4a:** o job diário `collect_installments` trava conta, linha do patrimônio, contrato e parcela, nessa ordem, confirma que a parcela ainda está em aberto e debita; sem saldo, marca `OVERDUE`, avisa a IF e tenta de novo no dia seguinte. A última parcela quita o contrato (`PAID_OFF`).
2. **4b:** o pagamento avulso (`POST /loan/{loan_key}/payment`) exige `Idempotency-Key`, trava conta, linha, contrato e parcelas em aberto e aplica o valor da parcela vencida mais antiga para a mais nova, e as futuras a valor presente.
3. Nos dois casos, só o principal amortizado volta ao limite, e volta à linha do patrimônio: o que a PF paga libera limite também para o MEI dela. Multa, mora e renegociação são da IF.

#### Fluxo 5 — Extrato paginado

&#91;image: Fluxo 5 — extrato paginado\]

O extrato (`GET /account/{account_key}/statement`) lê o ledger por keyset (`(created_at, id) < cursor`, `LIMIT n + 1`) e devolve itens, saldo, saldo bloqueado, disponível e `next_cursor`. O cursor é opaco (base64url de data e id); adulterado, `400 QIT000010`. Compra no crédito fica na fatura; HOLD de débito aparece como saldo bloqueado, não como lançamento. O extrato é por conta: a PF e cada CNPJ veem as próprias contas.

#### Fluxo 6 — Cartões de débito e crédito, carteira, fatura e rotativo

**6a · Carteira de crédito e emissão de cartão**

&#91;image: Fluxo 6a — carteira de crédito e emissão de cartão\]

**6b · Autorização, captura e estorno**

&#91;image: Fluxo 6b — autorização, captura e estorno\]

**6c · Fatura e rotativo**

&#91;image: Fluxo 6c — fatura e rotativo\]

A carteira de crédito é da conta e tem o limite, o ciclo e os encargos; o cartão virtual, o físico e a reemissão consomem o mesmo limite e caem na mesma fatura. Cartão só de débito não tem carteira.

1. A processadora chama `POST /card/authorization` em nome da IF emissora; `authorization_id` repetido devolve a mesma resposta, e recusa responde `200 DECLINED`, nunca `4xx`. Trava a conta e, se houver, a carteira; a primeira regra que falha decide o motivo: função do cartão, cartão `ACTIVE`, conta `ACTIVE`, carteira `ACTIVE` (crédito), limite ou saldo.
2. **Débito:** confere o saldo disponível e cria um HOLD (`held_balance`); a captura (`POST /card/captures`) troca o HOLD pelo valor capturado e lança `DEBIT_PURCHASE`. O HOLD não capturado deve ser liberado em 7 dias pelo job `expire_authorizations`.
3. **Crédito:** confere `total_limit − used_limit` e reserva; a captura vira itens nas faturas da carteira (a parcela k cai k−1 meses depois; os centavos que sobram da divisão vão na primeira; fatura nova nasce `OPEN` se a carteira não tem uma aberta, senão `FUTURE`), com vencimento ajustado a dia útil. O fechamento no dia de corte é do job `close_invoices`.
4. Estorno (`POST /card/refunds`) é evento (`REFUND` ou `PARTIAL_REFUND`), e a autorização segue `CAPTURED`. O pagamento da fatura (`POST /invoice/{invoice_key}/payment`) debita a conta e devolve o limite da carteira; fatura quitada fica `PAID`.
5. **Rotativo:** fatura não quitada no vencimento fica `PARTIALLY_PAID` ou `OVERDUE` e grava `original_debt_amount`. A IF lança o encargo (`REVOLVING` ou `INSTALLMENT_PLAN`) em `POST /invoice/{invoice_key}/charge`; se juros e encargos acumulados passarem de 100% da dívida original (Lei 14.690/2023), a resposta é `422` (QIT001061); dentro do teto, o encargo vira `REVOLVING_CHARGE` na própria fatura vencida e consome limite da carteira.

### Divergências conhecidas entre código, banco e este RFC

Os pontos da conferência de 08/10/2026 (parâmetros `*_id` nos resources, rota de DELETE da chave Pix, caminhos antigos nos testes, models com `id` UUID, FKs `UUID → BIGINT` no `database.sql` e as regras da devolução de Pix) foram corrigidos. Os models mapeiam as colunas `enum_*` com `PgEnum` (`src/models/types.py`).

Resta um, de documentação: os diagramas do `fluxo-v8` ainda mostram os caminhos no plural.

As premissas D1 (o teto conta só o principal em aberto), D2 (sócio PF e sociedade têm tetos separados) e D3 (a base do rotativo é a `original_debt_amount`) estão aplicadas no código e nos testes. Se o time ou o Jurídico decidir diferente, mudam o controller e os testes `test_cash_goes_out_of_the_account_and_only_principal_returns_to_the_limit`, `test_ltda_of_a_partner_has_its_own_ceiling` e `test_charge_lands_on_the_overdue_invoice_up_to_the_original_debt`.

## Referências

### Infraestrutura bancária

- [Documentação QI Tech](https://docs.qitech.com.br/) — padrão de referência da nossa API: contas digitais, Pix, TED, cartões e contas escrow.
- [PostgreSQL 16 — Explicit Locking](https://www.postgresql.org/docs/16/explicit-locking.html) — como funciona a trava de linha (`SELECT … FOR UPDATE`) e a regra que usamos contra deadlock: travar sempre na mesma ordem.
- [Stripe — Designing robust and predictable APIs with idempotency](https://stripe.com/blog/idempotency) — por que toda rota que move dinheiro exige `Idempotency-Key`.
- [Modern Treasury — Accounting for Developers, Part I](https://www.moderntreasury.com/journal/accounting-for-developers-part-i) — partidas dobradas explicadas para quem escreve o ledger.
- [ISO 8583 — códigos de resposta do campo 39](https://testdocs.nibss-plc.com.ng/pos/pos-interface-specifications-iso-8583-1987-version/data-element-definition-de39-de48) — significado dos códigos `00`, `14`, `51`, `57` e `62` que a autorização de cartão devolve.
- [BCB regulamenta o Banking as a Service: Resolução Conjunta nº 16/2025 (InfoMoney)](https://www.infomoney.com.br/?p=3121899) — responsabilidades de quem presta e de quem contrata BaaS; contratos vigentes se adequam até 31/12/2026.

### Microcrédito e regras legais

- [Lei 13.636/2018 — PNMPO](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13636.htm) — cria o programa de microcrédito produtivo orientado; público de pessoas naturais e jurídicas com renda ou receita até o teto da microempresa.
- [Resolução CMN 4.854/2020](https://www.normasbrasil.com.br/norma/resolucao-4854-2020_401868.html) — regras do microcrédito produtivo orientado: juros até 4% a.m., TAC até 3%, prazo mínimo e tetos de R$ 21 mil na mesma IF e R$ 80 mil no SFN por tomador.
- [Lei Complementar 123/2006, art. 3º](https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm) — microempresa tem receita bruta anual de até R$ 360 mil, o teto de elegibilidade.
- [STJ: MEI e EI respondem com o patrimônio pessoal (Diário do Comércio)](https://diariodocomercio.com.br/legislacao/mei-e-ei-tem-direito-a-gratuidade-de-justica/) — base para somar a PF e o EI/MEI dela no mesmo patrimônio.
- [Resolução BCB 19/2020: Pix gratuito para pessoa natural, inclusive empresário individual (Correio Braziliense)](https://www.correiobraziliense.com.br/economia/2020/10/4879215-pix-sera-gratuito-para-pessoas-fisicas-e-empreendedores-individuais.html) — por que o segmento de tarifa trata EI/MEI como pessoa física.
- [Código de Defesa do Consumidor, art. 52](https://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm) — multa de mora de até 2% e direito à quitação antecipada com redução proporcional dos juros.
- [Lei 14.690/2023, art. 28](https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2023/lei/l14690.htm) — juros e encargos do rotativo e do parcelamento da fatura não passam do valor original da dívida.
- [PL 1.472/2026: reajuste anual dos tetos do microcrédito (Tribuna do Sertão)](https://tribunadosertao.com.br/politica/2026/06/30/931290-reajuste-anual-dos-limites-do-microcredito-segue-para-a-camara) — propõe corrigir os tetos de R$ 21 mil e R$ 80 mil pelo IGP-M todo ano; o Senado aprovou em 08/07/2026 ([Atlas Público](https://atlaspublico.com.br/senado/noticias/senado-aprova-atualizacao-anual-dos-limites-de-saldo-69560)).
