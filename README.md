# Bootcamp QI Tech — projeto base da API

Projeto base do Bootcamp: uma API REST em **Python + FastAPI**, com banco
**PostgreSQL**, rodando em **Docker**.

Você não precisa saber programar para começar. A API e o banco sobem
no **Docker**, então você não instala nem um nem outro na sua máquina.
Os **testes** rodam no seu Python — são dois comandos, e a seção 2
mostra os dois.

---

## 0. O que você precisa ter instalado

São três coisas.

| O quê | Para quê | Como conferir |
|---|---|---|
| **Docker** (com o Docker Desktop no Mac/Windows) | roda a API e o banco | `docker compose version` |
| **Git** | trazer o projeto para o seu computador | `git --version` |
| **Python 3.11 ou mais novo** | rodar os testes (seção 2) | `python3 --version` |

Abra o terminal e rode os três comandos da coluna da direita. Se todos
responderem um número de versão, você está pronto.

> **Por que o Python, se tudo roda no Docker?** Porque os testes rodam
> FORA dele, na sua máquina, contra a API que está de pé no container.
> O ganho é o ciclo: você salva um teste e roda na hora, sem esperar
> imagem nenhuma ser montada. O preço está explicado na seção 2.

> **`docker compose version` deu erro?** Sua instalação do Docker é
> antiga demais (ou o Docker não está ligado). No Mac e no Windows,
> abra o **Docker Desktop** e espere a baleia parar de se mexer. Se o
> comando continuar falhando, reinstale pelo site oficial —
> o `docker compose` (com **espaço**) vem junto desde 2022.

Nada além destes três. Se em algum momento este projeto pedir que você
instale outro PROGRAMA, é um bug do projeto — avise a gente. (As
bibliotecas Python que os testes usam são outra conversa: elas entram
com um `pip install` na seção 2, dentro de uma pasta do próprio
projeto, e somem quando você apaga essa pasta.)

---

## 1. Rodando pela primeira vez

```bash
docker compose up
```

Um comando. Só isso, e não precisa criar nem copiar arquivo nenhum
antes: as configurações já vêm com valor padrão dentro do
`docker-compose.yml`.

O Docker baixa o Python, sobe o banco, cria as tabelas e liga a API. Na
primeira vez demora alguns minutos; depois é quase instantâneo.

São duas coisas de pé, e vale saber o nome de cada uma:

| Serviço | O que é |
|---|---|
| `api` | a API que responde às suas requisições |
| `db` | o banco de dados (PostgreSQL) |

Quando aparecer `Application startup complete`, a API está no ar. Abra
no navegador:

### 👉 http://localhost:3000

Você vai ver isto:

```json
{"service":"bootcamp-api","id":"8"}
```

Pouca coisa, e de propósito: essa rota só diz "estou viva, e eu sou este
serviço". Mas você acabou de fazer uma **requisição HTTP** — a mesma
coisa que o navegador faz ao abrir qualquer site.

### Agora as outras rotas

Elas não abrem no navegador, porque exigem um cabeçalho: o
`INTERNAL-TOKEN`, que é a senha da API (seção 6). Para mandar um
cabeçalho a gente usa o `curl`, um programa de linha de comando que já
vem instalado no Mac, no Linux e no Windows.

**Abra um segundo terminal** — o primeiro está ocupado rodando a API — e
cole um comando de cada vez.

> **No Windows**, use o **Git Bash**: ele veio junto com o Git da seção
> 0. No PowerShell estes comandos não funcionam, porque lá `curl` é o
> apelido de outro programa, com outra sintaxe.

O roteiro abaixo é a vida de um cliente do banco em sete passos: abre
conta, recebe um PIX, transfere para outra pessoa, confere o extrato e
pega um microcrédito. Todo dinheiro é em **centavos** (`50000` = R$ 500,00)
e todo documento vai **só com dígitos**.

#### 1. Abrir uma conta

O cliente do banco é o **titular**: um CPF (pessoa natural, `NATURAL`) ou
um CNPJ (pessoa jurídica, `LEGAL`). A Ana é pessoa física:

```bash
curl -X POST http://localhost:3000/customer \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "person_type": "NATURAL",
    "document": "39053344705",
    "name": "Ana Souza",
    "birth_date": "1990-05-17",
    "annual_revenue": 20000000
  }'
```

```json
{"customer_id":"d64144dd-1064-45d5-b174-d9e72e8c7708","account_id":"3480d0c5-b60d-4deb-9f0d-21905ab3e9cb","branch":"0001","account_number":"00000001","status":"ACTIVE","status_reason":null,"microcredit_eligible":true}
```

Um pedido criou duas coisas: o **titular** e a primeira **conta** dele.
Guarde o seu `customer_id`, o `account_id` (é o endereço da conta nesta
API) e o `account_number` (é o endereço que o PIX usa para chegar até
ela). Os seus nascem diferentes destes.

Renda de R$ 200 mil/ano deixa a Ana elegível ao microcrédito: o teto é
R$ 360 mil (`36000000` centavos).

A Ana também é MEI. No banco, o MEI é **outro titular**: o CNPJ dela,
com `legal_nature` `EI` e apontando para a PF dona. Ele tem conta
própria, mas responde com o mesmo patrimônio da Ana — isso volta no
passo 7.

```bash
curl -X POST http://localhost:3000/customer \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "person_type": "LEGAL",
    "document": "11222333000181",
    "name": "Ana Souza Doces",
    "legal_nature": "EI",
    "owner_customer_id": "SEU_CUSTOMER_ID",
    "annual_revenue": 20000000
  }'
```

> **Rodou duas vezes e levou 409?** É de propósito: o documento não pode
> se repetir (`QIT001010`). Para outro titular, troque o CPF ou o CNPJ
> por números **válidos de verdade** — os dígitos finais precisam bater
> com a conta.
>
> **E se a pessoa tiver 17 anos?** A conta nasce `REJECTED`, com 201, e
> não com erro: a tentativa fica guardada, porque banco precisa de trilha
> de auditoria. Com 80 anos ou mais, ou sendo pessoa politicamente
> exposta (`"is_pep": true`), nasce `PENDING`, esperando revisão. O CPF
> `52998224725` faz o papel de alguém em lista restritiva: nasce
> `REJECTED` por KYC (`src/utils/kyc_mock.py`).

#### 2. Ver a conta

```bash
curl http://localhost:3000/account/SEU_ACCOUNT_ID \
  -H "INTERNAL-TOKEN: default_token"
```

```json
{"account_id":"3480d0c5-...","customer_id":"d64144dd-...","branch":"0001","account_number":"00000001","status":"ACTIVE","status_reason":null,"status_events":[{"from_status":null,"to_status":"ACTIVE","reason":null,"created_at":"2026-10-09T11:36:47.292529-03:00"}],"balance":0,"held_balance":0,"available_balance":0,"microcredit_eligible":true,"created_at":"2026-10-09T11:36:47.292529-03:00"}
```

Três saldos, e a diferença importa: `balance` é o que a conta tem,
`held_balance` é o que está reservado (uma compra no débito ainda não
confirmada, por exemplo) e `available_balance` é o que dá para gastar.

#### 3. Receber um PIX

Não existe rota de "depósito" — num banco de verdade, dinheiro não
aparece do nada. Ele chega por um trilho de pagamento. Aqui, quem faz o
papel do **SPI** (o sistema do Banco Central que liquida o PIX) é você,
chamando o webhook:

```bash
curl -X POST http://localhost:3000/webhook/spi \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "RECEIVED",
    "external_id": "E0001",
    "amount": 50000,
    "destination_account": {"branch": "0001", "number": "SEU_ACCOUNT_NUMBER"},
    "sender": {"name": "Fulano", "document": "52998224725", "ispb": "00000000"}
  }'
```

```json
{"incoming_transfer_id":"b1e27679-a114-47c0-9c1e-cf69d65b96f6","rail":"SPI","pix_transfer_type":"MANUAL","external_id":"E0001","status":"CREDITED","amount":50000,"original_transfer_id":null}
```

Repita o comando: a resposta é a mesma, e o saldo **não** dobra. O SPI
pode entregar a mesma mensagem duas vezes, e o `external_id` é o que
garante que o crédito acontece uma vez só. Mande para uma conta que não
existe e o status vira `RETURNED` — devolução, ainda com 200, porque o
trilho só quer saber se a mensagem chegou.

#### 4. Transferir para outra conta (TEF)

Abra uma segunda conta (passo 1, com outro CPF — `11144477735`, por
exemplo) e transfira R$ 100,00 da primeira para ela:

```bash
curl -i -X POST http://localhost:3000/transfer \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 3f2b8c1e-5d4a-4e6b-9c7d-1a2b3c4d5e6f" \
  -d '{
    "source_account_id": "SEU_ACCOUNT_ID",
    "method": "TEF",
    "amount": 10000,
    "destination": {"account_id": "ACCOUNT_ID_DA_SEGUNDA_CONTA"}
  }'
```

```
HTTP/1.1 201 Created
{"transfer_id":"ba60383c-...","request_control_key":"3f2b8c1e-5d4a-4e6b-9c7d-1a2b3c4d5e6f","method":"TEF","status":"COMPLETED","amount":10000,"fee":100,"source_account_id":"d7030ca3-...","on_us":true,"destination":{"account_id":"02b24e5d-..."},"created_at":"2026-10-09T11:37:31.752683-03:00","completed_at":"2026-10-09T11:37:31.752683-03:00"}
```

Repare no `fee`: R$ 1,00 de tarifa, cobrada da origem. E rode o mesmo
comando de novo, **igualzinho**: volta `200 OK`, com o mesmo corpo, e o
dinheiro não sai outra vez. É o `Idempotency-Key`, um **UUID v4** que o
cliente gera (`uuidgen` no terminal faz um). Quem clica duas vezes no
botão de "transferir" manda o mesmo pedido duas vezes — e a chave é o
que deixa a API reconhecer a repetição. Sem o cabeçalho, ou com algo que
não é UUID v4, a API recusa (`QIT001015`); com a mesma chave e um valor
diferente, recusa também (`QIT001016`), porque aí não é repetição, é
engano.

#### 5. Ver o extrato

```bash
curl "http://localhost:3000/account/SEU_ACCOUNT_ID/statement" \
  -H "INTERNAL-TOKEN: default_token"
```

```json
{"account_id":"d7030ca3-...","balance":39900,"held_balance":0,"available_balance":39900,
 "items":[
  {"entry_id":5,"type":"TRANSFER_FEE","method":"TEF","amount":-100,"balance_after":39900,"reference_type":"TRANSFER","reference_id":"ba60383c-...","external_id":null,"created_at":"..."},
  {"entry_id":3,"type":"TEF_SENT","method":"TEF","amount":-10000,"balance_after":40000,"reference_type":"TRANSFER","reference_id":"ba60383c-...","external_id":null,"created_at":"..."},
  {"entry_id":2,"type":"PIX_RECEIVED","method":"PIX","amount":50000,"balance_after":50000,"reference_type":"INCOMING_TRANSFER","reference_id":"fea6168a-...","external_id":"E0001","created_at":"..."}],
 "next_cursor":null}
```

Do mais novo para o mais antigo, e cada linha diz o saldo **depois**
dela: 500,00 → 400,00 → 399,00. A TEF virou duas linhas (a transferência
e a tarifa), e as duas apontam para a mesma `reference_id`.

Por trás de cada linha do cliente existe a outra ponta: a tarifa entrou
numa conta interna de receita, o PIX saiu de uma conta interna do SPI.
Somando todas as contas do banco, o resultado é sempre **zero** — é o
que se chama partidas dobradas, e o próprio banco de dados recusa
gravar uma operação que não feche.

Para paginar, use `?limit=` (até 100) e, nas páginas seguintes,
`?cursor=` com o `next_cursor` que veio. O `next_cursor` nulo é a
resposta para "tem mais?".

#### 6. Mandar um JSON torto

```bash
curl -X POST http://localhost:3000/customer \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{}'
```

```json
{"title":"Bad Request","description":"'legal_nature' is a required property","translation":"Payload Inválido","code":"QIT000001"}
```

**400**, e nada foi criado. Quem recusou não foi a regra de negócio: foi
o `src/schemas/`, antes da primeira linha da rota rodar. A validação para
no primeiro problema — vá preenchendo um campo de cada vez para ver a
reclamação andar.

Agora um CPF com o formato certo e os dígitos errados:

```bash
curl -X POST http://localhost:3000/customer \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{"person_type":"NATURAL","document":"11122233344","name":"X","birth_date":"1990-01-01","annual_revenue":0}'
```

```json
{"title":"Invalid Document Number","description":"The document number 11122233344 is not a valid CPF.","translation":"O CPF informado não é válido.","code":"QIT001003"}
```

Agora é **422**, não 400. A diferença não é capricho: 400 quer dizer
"não consegui ler o seu pedido"; 422 quer dizer "li, entendi, e esse
valor não pode existir". O schema sabe contar onze dígitos — ele não
sabe fazer a conta dos dois últimos. Quem sabe é o
`src/utils/document_number.py`, e por isso essa recusa vem de dentro,
com código próprio.

O schema também recusa o que não conhece. Erre o nome de um parâmetro de
propósito:

```bash
curl "http://localhost:3000/account/SEU_ACCOUNT_ID/statement?limt=10" \
  -H "INTERNAL-TOKEN: default_token"
```

```json
{"title":"Bad Request","description":"Additional properties are not allowed ('limt' was unexpected)","translation":"Payload Inválido","code":"QIT000001"}
```

Sem essa recusa, o `limt` com a letra trocada seria ignorado e a página
viria com o tamanho padrão, como se o pedido tivesse funcionado — o pior
tipo de bug, o que não reclama.

#### 7. Pegar um microcrédito

Quem decide o crédito é a instituição financeira (IF): ela informa a
linha do **patrimônio** da Ana — R$ 15 mil, 3% ao mês de juros e 2% de
TAC (a tarifa de abertura):

```bash
curl -X PUT http://localhost:3000/customer/SEU_CUSTOMER_ID/credit_line \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{"total_limit": 1500000, "monthly_interest_rate": 0.03, "origination_fee_rate": 0.02}'
```

```json
{"credit_line_id":"71ac8e8c-...","customer_id":"d64144dd-...","version":1,"total_limit":1500000,"available_limit":1500000,"microcredit_balance":0,"monthly_interest_rate":0.03,"origination_fee_rate":0.02,"updated_at":"..."}
```

A regra do microcrédito (Res. CMN 4.854/2020) está na API: limite acima
de R$ 21 mil, juros acima de 4% ao mês ou TAC acima de 3% voltam **422**
(`QIT001055`). E a linha é uma só para a Ana e o MEI dela: peça a do MEI
(`GET /customer/CUSTOMER_ID_DO_MEI/credit_line`) e volta a mesma.

Antes de contratar, simule — nada é gravado:

```bash
curl -X POST http://localhost:3000/account/SEU_ACCOUNT_ID/loan/simulation \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{"amount": 300000, "installment_count": 3}'
```

```json
{"amount":300000,"installment_count":3,"term_days":90,"monthly_interest_rate":0.03,"effective_fee_rate":0.015,"origination_fee_amount":4500,"net_amount":295500,"effective_cost_monthly":0.037901,"effective_cost_annual":0.562684,
 "installments":[
  {"number":1,"due_date":"2026-11-09","principal_amount":97059,"interest_amount":9000,"total_amount":106059},
  {"number":2,"due_date":"2026-12-08","principal_amount":99971,"interest_amount":6088,"total_amount":106059},
  {"number":3,"due_date":"2027-01-07","principal_amount":102970,"interest_amount":3089,"total_amount":106059}]}
```

Três coisas para reparar. A TAC caiu para **1,5%**: abaixo de 120 dias
ela é proporcional ao prazo (90/120 × 2%). As parcelas são **iguais**
(sistema Price), mas os juros caem a cada mês, porque incidem sobre o
que falta pagar. E o `effective_cost_monthly` (o CET) é maior que os 3%
de juros: é o custo de verdade, com a TAC dentro.

Para contratar, o mesmo corpo com `purpose` e a declaração de dívida no
sistema financeiro — e, como todo POST que mexe com dinheiro, um
`Idempotency-Key`:

```bash
curl -i -X POST http://localhost:3000/account/SEU_ACCOUNT_ID/loan \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 9b1d2c3e-4f5a-4b6c-8d7e-0f1a2b3c4d5e" \
  -d '{"amount": 300000, "installment_count": 3, "purpose": "capital de giro", "sfn_debt_declaration": true}'
```

Volta `201` com o contrato e as parcelas, e os R$ 2.955,00 líquidos já
estão na conta: no extrato aparecem o `DISBURSEMENT` (+3.000,00) e a
`ORIGINATION_FEE` (−45,00). Agora tente pegar R$ 13 mil pela conta do
MEI:

```json
{"title":"INSUFFICIENT_LIMIT","description":"Amount 1300000 is above the available limit 1200000.","translation":"Valor acima do limite disponível da linha.","code":"QIT001057"}
```

Sobraram R$ 12 mil — para os dois. O teto é do patrimônio, não da conta:
se a Ana e o MEI pedissem ao mesmo tempo, um esperaria o outro, e a soma
nunca passaria do limite.

As parcelas vencem sozinhas: quem cobra é o **job** `collect_installments`,
que roda uma vez por dia (seção "Todas as rotas", lá embaixo). Para pagar
antes, ou quitar com desconto, é `POST /loan/{loan_id}/payment`.

#### Esqueceu o `-H "INTERNAL-TOKEN: ..."`?

A API responde **403** e nem chega a olhar o resto:

```json
{"title":"Forbidden","description":"Request must be internal","translation":"Requisição precisa ser interna","code":"QIT000002"}
```

#### Toda resposta vem com um número de protocolo

Repare no `-i` deste comando: ele mostra os **cabeçalhos** da resposta,
não só o corpo.

```bash
curl -i "http://localhost:3000/account/SEU_ACCOUNT_ID/statement?limit=1" \
  -H "INTERNAL-TOKEN: default_token"
```

```
HTTP/1.1 200 OK
content-type: application/json
x-request-id: 52d8e778-cc48-4b45-a3e4-14b4597d1e15
...
```

Esse `x-request-id` é o **número de protocolo** da sua requisição: um
nome único, criado no instante em que ela chegou. Copie o seu e procure
por ele no log:

```bash
docker compose logs api | grep 52d8e778
```

```
[INFO] bootcamp-api.middlewares.request_logger [52d8e778-...] - ENTROU GET /account/f1190d11-.../statement?limit=1
[INFO] bootcamp-api.middlewares.request_logger [52d8e778-...] - SAIU 200 GET /account/f1190d11-.../statement - 7.2 ms
```

Duas linhas, o mesmo nome nas duas — e nenhuma outra requisição usa esse
nome. Serve para o dia em que alguém disser "deu erro por volta das
14h30": sem o número, você abre o log e encontra mil linhas parecidas, de
mil requisições diferentes, embaralhadas, porque a API atende várias ao
mesmo tempo e o log é um só. Com o número, achar a agulha é um `grep`.

Se quem chamou já mandar um `x-request-id`, a API **respeita o que veio**
e usa o mesmo — é assim que se segue um único pedido atravessando vários
sistemas:

```bash
curl -i "http://localhost:3000/account/SEU_ACCOUNT_ID/statement?limit=1" \
  -H "INTERNAL-TOKEN: default_token" \
  -H "X-Request-ID: meu-teste-1"
```

Experimente mandar um valor esquisito nesse cabeçalho — com espaços, ou
bem comprido. A API não devolve o que você mandou: ela troca por um novo.
O porquê está em `src/utils/request_context.py`, e é uma das poucas
lições de segurança que cabem em cinco linhas.

> Só o `/` e o `/health_check` não aparecem no log: o Docker consulta o
> health check a cada três segundos, e sem essa exceção o log seria
> quase só isso. Eles ganham o `x-request-id` como todo mundo — o que
> não ganham é a linha de log.

### Todas as rotas

Cinquenta e uma rotas respondem hoje. O contrato completo — com corpo,
erros e regras de cada uma — está em **`docs/api-contract.md`**.

| Método e rota | O que faz | Responde |
|---|---|---|
| `GET /` | diz qual serviço é este | `200` + nome e id |
| `GET /health_check` | diz se a API está de pé | `204`, sem corpo |
| `POST /customer` | cadastra o titular (CPF ou CNPJ) e abre a primeira conta | `201` + ids e status da conta |
| `GET /customer/{id}` · `PATCH /customer/{id}` | busca o titular · atualiza a renda (e a elegibilidade) | `200` |
| `POST /customer/{id}/account` · `GET /customer/{id}/account` | abre mais uma conta · lista as contas do titular | `201` · `200` |
| `POST /customer/{id}/relationship` | liga sócio, administrador ou procurador (PF) a uma PJ | `201` |
| `GET /account/{id}` | busca a conta, com os três saldos | `200` + a conta |
| `PATCH /account/{id}/status` | muda o status (`ACTIVE`, `REJECTED`, `BLOCKED`, `CLOSED`) | `200` + a conta |
| `GET /account/{id}/statement` | extrato, do mais novo ao mais antigo | `200` + a página |
| `PUT /customer/{id}/credit_line` · `GET` | linha de microcrédito do patrimônio | `200` |
| `POST /account/{id}/loan/simulation` | simula o empréstimo, sem gravar | `200` |
| `POST /account/{id}/loan` · `GET /account/{id}/loan` | contrata (exige `Idempotency-Key`) · lista os contratos | `201` · `200` |
| `GET /loan/{id}` · `POST /loan/{id}/payment` | contrato com parcelas · pagamento avulso ou antecipado | `200` · `201` |
| `POST /transfer` | TEF — exige `Idempotency-Key` (UUID v4) | `201` (ou `200` na repetição) |
| `GET /transfer/{id}` · `PATCH /transfer/{id}/cancel` | busca a transferência · cancela um agendamento | `200` |
| `GET /account/{id}/transfer` | transferências em que a conta é origem ou destino | `200` + a página |
| `POST /account/{id}/pix_key` · `GET` · `DELETE …/pix_key/{pix_key_id}` | chaves Pix da conta | `201` · `200` · `200` |
| `GET /pix_key/{chave}?account_id=` | consulta ao DICT (mock): devolve o `end_to_end_id` | `200` |
| `POST /account/{id}/pix_transfer` | Pix por chave ou manual — exige `Idempotency-Key` | `201` on-us · `202` externo |
| `POST /account/{id}/incoming_transfer/{id}/reversal` | devolve um Pix recebido | `202` |
| `POST /account/{id}/ted_transfer` | TED agora ou agendada | `202` |
| `POST /webhook/spi` · `POST /webhook/str` | papel dos trilhos: entrada, liquidação, rejeição, devolução | `200`, sempre |
| `POST /account/{id}/credit_wallet` | carteira de crédito (limite, ciclo, encargos) | `201` |
| `GET /credit_wallet/{id}` · `PATCH …/limit` · `PATCH …/status` | consulta e manutenção da carteira | `200` |
| `GET /credit_wallet/{id}/invoice` · `GET /invoice/{id}` | faturas | `200` |
| `POST /invoice/{id}/payment` · `POST /invoice/{id}/charge` | paga a fatura · lança encargo do rotativo — exigem `Idempotency-Key` | `201` |
| `POST /account/{id}/card` · `GET /account/{id}/card` | emite e lista cartões | `201` · `200` |
| `GET /card/{id}` · `PATCH …/activate` · `PATCH …/status` | consulta, ativação do físico, status | `200` |
| `POST /card/authorization` | autorização da rede | `200`, sempre |
| `GET /card/authorization/{id}` · `POST …/increment` · `POST …/reversal` | autorização: consulta, incremental, reversão | `200` |
| `POST /card/captures` · `POST /card/refunds` | captura e estorno | `200` |
| `POST /job/{nome}` | roda um dos 8 jobs agendados agora | `200` + o que processou |

Os **jobs** são as tarefas do dia a dia do banco que ninguém pede: cobrar
parcelas vencidas, fechar e vencer faturas, fazer o débito automático,
executar TED agendada, conciliar com os trilhos, expirar autorizações de
cartão e avisar a IF dos eventos. São oito, e todos podem rodar duas vezes
sem mexer no dinheiro de novo. Quem agenda é a IF; para rodar um na mão:

```bash
curl -X POST http://localhost:3000/job/collect_installments \
  -H "INTERNAL-TOKEN: default_token"
```

```json
{"job":"collect_installments","result":{"processed":0,"outcomes":{}}}
```

O mesmo job roda pela linha de comando, dentro do container:
`docker compose exec api python -m jobs.collect_installments`. A lista
dos oito está em `docs/api-contract.md`.

Todas, menos as duas de cima, exigem o `INTERNAL-TOKEN` (seção 6). As duas de cima
são abertas — a primeira você já usou: foi ela que respondeu no
navegador.

Para desligar tudo: `Ctrl+C` no terminal da API e depois

```bash
docker compose down
```

---

## 2. Rodando os testes

Os testes rodam **na sua máquina**, contra a API que está de pé no
Docker. Então são dois passos: um de uma vez só, outro toda vez.

**Uma vez só — instalar as dependências de teste:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

O `.venv` é uma pasta com um Python só deste projeto. Ele existe pra que
instalar algo aqui não mexa no Python da sua máquina — e pra que apagar a
pasta desfaça tudo. No Windows, a segunda linha é
`.venv\Scripts\activate`.

**Toda vez — com a API de pé, em outro terminal:**

```bash
pytest
```

A API precisa estar respondendo antes. Se você acabou de dar
`docker compose up`, espere o `(healthy)` aparecer — é o healthcheck do
`docker-compose.yml` dizendo que a porta já atende. Sem isso, o primeiro
teste bate numa porta que ainda não responde.

O resultado sai assim:

```
tests/integration/test_healthcheck.py::TestHealthCheck::test_home PASSED
...
============================= 193 passed in 25.30s =============================
```

Para rodar só um arquivo (ou só um teste), acrescente o caminho:

```bash
pytest -v tests/integration/test_healthcheck.py
```

Os testes leem o seu `.env` sozinhos (é o `tests/conftest.py` que faz
isso). Trocou a porta da API ali, os testes passam a bater na porta nova
— você não configura a mesma coisa em dois lugares.

Os testes conversam com a API **por HTTP**, exatamente como um cliente de
verdade faria. Eles não espiam o código por dentro: nenhum deles importa
nada de `src/`. Só sabem: "mandei isso, tem que voltar aquilo".

> Uma exceção, e ela é honesta: `tests/utils/db_utils.py` fala com o
> banco direto, por SQLAlchemy, para duas coisas. A primeira é **zerar**
> o banco entre testes que não podem se atrapalhar. A segunda é mexer no
> **calendário**: vencer uma parcela, passar o fechamento de uma fatura,
> expirar uma autorização — coisas que, pela API, só o tempo faz. Essas
> escritas moram em helpers com nome (`tests/utils/object_generator.py`),
> e nenhum teste **lê** o banco para conferir resultado: a conferência
> vem sempre da resposta da API. O resto do cenário nasce pela API, com
> `POST`.

Isso tem uma consequência bonita: **este projeto inteiro já foi reescrito
de um framework para outro, e nenhum teste precisou mudar.** Quando o
teste descreve o combinado em vez de descrever o código, ele sobrevive à
reforma.

## 3. Quando dá errado

Os tropeços mais comuns, com a mensagem que você vai ver:

### `port is already allocated`

```
Bind for 0.0.0.0:5432 failed: port is already allocated
```

Outro programa da sua máquina já usa aquela porta (é comum ter um
Postgres instalado ocupando a 5432). Não precisa descobrir qual: escolha
outras portas livres. É pra isto que serve o `.env` —

```bash
cp .env.example .env
```

— e, dentro dele, tire o `#` da frente destas duas linhas e troque os
números:

```
API_PORT=3001
DB_PORT=5433
```

Mexeu no `DB_PORT`? Então mude **também** a porta da `DATABASE_URL`, no
mesmo arquivo:

```
DATABASE_URL=postgresql+psycopg2://bootcamp:bootcamp@localhost:5433/bootcamp
```

São dois lugares porque são dois pontos de vista. O `DB_PORT` diz em
que porta **da sua máquina** o banco aparece; a `DATABASE_URL` é o
endereço que os testes usam para chegar nele de fora do Docker. A API
lá dentro não usa nenhuma das duas — para ela o banco é `db:5432`, e
por isso essa linha está fixa no `docker-compose.yml`.

Suba de novo. Agora a API atende em http://localhost:3001 — e nos
comandos `curl` da seção 1 você troca `3000` por `3001`.

### `failed to connect to the docker API`

```
failed to connect to the docker API at unix:///var/run/docker.sock;
check if the path is correct and if the daemon is running
```

O Docker não está ligado. Abra o **Docker Desktop** (Mac/Windows) e
espere ficar verde. No Linux: `sudo systemctl start docker`.

### `Não consegui falar com a API` / `Não consegui falar com o banco`

Só aparece no atalho local (fora do Docker). Quer dizer que a API ou o
banco não estão de pé, ou que a porta no seu `.env` não é a que eles
estão usando. Suba com `docker compose up` e confira as portas.

### `relation "..." does not exist`

```
psycopg2.errors.UndefinedTable: relation "minha_tabela" does not exist
```

Você mexeu no `database/database.sql`, e o banco não ficou sabendo.
Aquele arquivo roda **uma vez só: quando o banco nasce.** Depois disso o
Postgres nunca mais olha para ele — subir de novo com `docker compose
up` não adianta, e `docker compose restart db` também não.

Repare no que a mensagem faz com você: ela não diz "seu SQL não rodou",
diz que a tabela não existe. Você vai reler o seu SQL procurando um erro
de digitação que não está lá.

> **E nunca use o caractere de porcentagem nesse arquivo**, nem em
> comentário: o reset dos testes (`tests/utils/db_utils.py`) roda o SQL
> pelo psycopg2, que trata esse caractere como marcador de parâmetro. O
> sintoma é um erro no reset, longe do SQL que causou.

Para o banco nascer de novo, já com o schema novo:

```bash
docker compose down -v
docker compose up
```

O `-v` é o que apaga o volume — o disco do banco. **Ele leva junto tudo
que você tinha criado na mão**, as entidades dos `curl` da seção 1. Não
tem meio-termo: ou o banco nasce de novo com o schema novo, ou continua
com o antigo. (Em sistema de verdade é outra história — lá ninguém apaga
o banco, e a mudança de schema entra por um comando aplicado no deploy.)

### Nada disso resolveu?

Este comando desliga e limpa **este** projeto (containers, rede e o
banco com tudo dentro) para você recomeçar do zero:

```bash
docker compose down -v
docker compose up
```

Para ver o que a API está dizendo enquanto roda: `docker compose logs -f api`.

---

## 4. As pastas

```
src/
  app.py           ← liga tudo: rotas, middlewares e tratamento de erro
  database.py      ← onde a sessão de banco mora (quem cuida do ciclo
                     dela é middlewares/session_manager.py)
  constants.py     ← as configurações, lidas do ambiente

  resources/       ← recebe a requisição HTTP e devolve a resposta
                     (quem liga cada endereço a um resource é o app.py)
  schemas/         ← o formato do que entra: o JSON do corpo e os
                     parâmetros do endereço
  controllers/     ← as regras de negócio: o que pode e o que não pode
  repositories/    ← as conversas com o banco
  models/          ← as tabelas, descritas em Python
  dtos/            ← traduz o objeto do banco no JSON que sai
  errors/          ← os erros da API, cada um com seu código
  middlewares/     ← o que acontece com TODA requisição
  connectors/      ← as conversas com outros serviços
  utils/           ← as ferramentas que não são de nenhuma camada
  jobs/            ← os 8 jobs agendados, um comando por job
                     (`python -m jobs.<nome>`; a regra mora no controller)

database/
  database.sql     ← as tabelas, em SQL puro (o schema v7)

tests/             ← os testes
```

### Por que tanta pasta?

Porque cada uma tem **um trabalho só**, e só conversa com a vizinha:

```
requisição → resource → controller → repository → banco
                 ↑           ↑
             valida o     decide o
              formato     que pode
```

O resource não sabe SQL. O repository não sabe o que é uma regra de
negócio. Um teste rápido para saber se uma linha está na pasta certa:
**nenhum `raise` mora em `resources/`** — quem recusa é o schema, antes,
ou o controller, depois. Confira você mesmo:

```bash
grep -rn "raise" src/resources/
```

Não volta nada, e isso é de propósito. Quando você precisa trocar o banco, mexe numa pasta. Quando a
regra muda, mexe na outra. É isso que permite um time inteiro trabalhar
no mesmo projeto sem pisar no pé um do outro.

---

## 5. Configuração e senhas

Toda configuração entra por **variável de ambiente** — nunca escrita no
meio do código.

- **valor padrão** → escrito no `docker-compose.yml`, na forma
  `${VARIAVEL:-padrao}`. É por causa dele que o `docker compose up`
  funciona sem preparo nenhum.
- `.env` → **opcional**, fica só na sua máquina e **nunca** vai para o
  Git. Serve para sobrescrever um padrão (porta ocupada, outro token).
- `.env.example` → vai para o Git, e é a cópia de onde você parte. Só
  tem valor de mentirinha.

Essa separação não é frescura. Senha commitada em repositório é uma das
formas mais comuns de vazamento de dados no mundo real, e não tem
desfazer: uma vez no histórico, está lá para sempre.

Uma ressalva honesta: valor padrão de senha em arquivo versionado só
vale porque aqui é um projeto de estudo, sem dado de ninguém. Em
sistema de verdade, segredo não tem padrão — ele falta, e a aplicação
se recusa a subir sem ele.

## 6. Autenticação

As rotas de negócio pedem um cabeçalho:

```
INTERNAL-TOKEN: default_token
```

Sem ele, a API responde **403**. `default_token` é o valor padrão; para
trocar, ponha `INTERNAL_TOKEN=outra_coisa` no seu `.env`.

Ficam abertas, de propósito, só duas: a rota raiz e o `/health_check`
— esta última porque quem a consulta é o próprio Docker, que não tem
como mandar cabeçalho.

---

## 7. Os códigos de erro

Todo erro da API responde no mesmo formato, com um código próprio:

```json
{
  "title": "Bad Request",
  "description": "'legal_nature' is a required property",
  "translation": "Payload Inválido",
  "code": "QIT000001"
}
```

| Código      | HTTP | Quando acontece                                       |
|-------------|------|-------------------------------------------------------|
| `QIT000001` | 400  | o JSON (ou a query string) está fora do formato       |
| `QIT000002` | 403  | faltou o `INTERNAL-TOKEN`, ou ele está errado         |
| `QIT000010` | 400  | parâmetro inválido (ex.: cursor adulterado)           |
| `QIT000404` | 404  | essa rota não existe                                  |
| `QIT000405` | 405  | a rota existe, mas não aceita esse método             |
| `QIT000500` | 500  | erro inesperado (o time é avisado)                    |
| `QIT001003` | 422  | o CPF tem o formato certo, mas não é um CPF           |
| `QIT001007` | 422  | a data de nascimento não existe no calendário         |
| `QIT001008` | 404  | cliente não encontrado                                |
| `QIT001009` | 404  | conta não encontrada                                  |
| `QIT001010` | 409  | já existe um cliente com esse CPF ou CNPJ             |
| `QIT001011` | 422  | o CNPJ tem o formato certo, mas não é um CNPJ         |
| `QIT001012` | 409  | mudança de status que a conta não permite             |
| `QIT001013` | 409  | a conta não está ativa para movimentar dinheiro       |
| `QIT001014` | 409  | encerramento com saldo, reserva ou empréstimo ativo   |
| `QIT001015` | 400  | faltou o `Idempotency-Key`, ou ele está malformado    |
| `QIT001016` | 409  | a mesma `Idempotency-Key` veio com outro conteúdo     |
| `QIT001017` | 422  | saldo insuficiente (valor + tarifa)                   |
| `QIT001018` | 422  | origem e destino são a mesma conta                    |
| `QIT001019` | 422  | limite noturno (20h–6h) excedido                      |
| `QIT001020` | 404  | transferência não encontrada                          |

Os demais códigos de domínio (`QIT001021` a `QIT001066`: Pix, TED,
cartões, faturas, titular v7 e microcrédito) estão na tabela completa de
`docs/api-contract.md`.

`QIT001001`, `001002`, `001004`, `001005` e `001006` estão **aposentados**:
eram do exemplo `sample_entity`, que saiu do projeto. Não reutilize —
quem integrou programou em cima do número, e um número velho com
significado novo é um bug que ninguém vê chegando.

Um código estável vale mais que uma mensagem bonita: quem integra com a
API programa em cima do código, não do texto.

Os números não são sorteados. Eles vêm em duas faixas:

- **`QIT000…`** — os erros que **toda** API tem: JSON errado, sem token,
  rota inexistente. Estão em `src/errors/base_error.py` e você não
  precisa mexer neles.
- **`QIT001…`** — os erros das **regras deste projeto**. Estão em
  `src/errors/custom_errors.py`, e é aí que os seus entram: o próximo
  livre é o `QIT001067`.

Não repita um número. Se repetir, a API **não sobe** — tem uma checagem
no start (`error_verification`, em `src/errors/base_error.py`) que
procura código repetido e derruba a aplicação de propósito. Parecer
chato agora é melhor que dois erros diferentes chegarem ao cliente com o
mesmo código.

---

## 8. A licença

Este projeto é **MIT** — pode usar, copiar, modificar e levar para o seu
portfólio, inclusive em trabalho pago. O único pedido é manter o arquivo
`LICENSE` junto quando você distribuir o código.