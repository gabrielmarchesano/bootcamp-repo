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

O roteiro abaixo é a vida de um cliente do banco em seis passos: abre
conta, recebe um PIX, transfere para outra pessoa e confere o extrato.
Todo dinheiro é em **centavos** (`50000` = R$ 500,00) e todo documento vai
**só com dígitos**.

#### 1. Abrir uma conta

```bash
curl -X POST http://localhost:3000/customers \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "cpf": "39053344705",
    "name": "Ana Souza",
    "birth_date": "1990-05-17",
    "type": "MEI",
    "cnpj": "11222333000181",
    "annual_revenue": 20000000
  }'
```

```json
{"customer_id":"8fb8e377-bd8b-4942-b368-662beb8ec82b","account_id":"f1190d11-1836-451a-8a1d-ff8772e663c0","branch":"0001","account_number":"00000001","status":"ACTIVE","status_reason":null,"microcredit_eligible":true}
```

Um pedido criou duas coisas: o **cliente** e a **conta** dele. Guarde o
seu `account_id` (é o endereço da conta nesta API) e o seu
`account_number` (é o endereço que o PIX usa para chegar até ela). Os
seus nascem diferentes destes.

Faturamento de R$ 200 mil/ano deixa a Ana elegível ao microcrédito: o
teto é R$ 360 mil (`36000000` centavos).

> **Rodou duas vezes e levou 409?** É de propósito: o CPF não pode se
> repetir (`QIT001010`). Para outra conta, troque CPF e CNPJ por números
> **válidos de verdade** — os dígitos finais precisam bater com a conta.
>
> **E se a pessoa tiver 17 anos?** A conta nasce `REJECTED`, com 201, e
> não com erro: a tentativa fica guardada, porque banco precisa de trilha
> de auditoria. Com 80 anos ou mais, ou sendo pessoa politicamente
> exposta (`"is_pep": true`), nasce `PENDING`, esperando revisão.

#### 2. Ver a conta

```bash
curl http://localhost:3000/accounts/SEU_ACCOUNT_ID \
  -H "INTERNAL-TOKEN: default_token"
```

```json
{"account_id":"f1190d11-...","customer_id":"8fb8e377-...","branch":"0001","account_number":"00000001","status":"ACTIVE","status_reason":null,"balance":0,"held_balance":0,"available_balance":0,"microcredit_eligible":true,"created_at":"2026-10-01T15:21:03.778479-03:00"}
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
curl -X POST http://localhost:3000/webhooks/spi \
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
{"incoming_transfer_id":"36abf9ec-ed98-4e21-a005-616855c69280","rail":"SPI","external_id":"E0001","status":"CREDITED","amount":50000}
```

Repita o comando: a resposta é a mesma, e o saldo **não** dobra. O SPI
pode entregar a mesma mensagem duas vezes, e o `external_id` é o que
garante que o crédito acontece uma vez só. Mande para uma conta que não
existe e o status vira `RETURNED` — devolução, ainda com 200, porque o
trilho só quer saber se a mensagem chegou.

#### 4. Transferir para outra conta (TEF)

Abra uma segunda conta (passo 1, com outro CPF) e transfira R$ 100,00
da primeira para ela:

```bash
curl -i -X POST http://localhost:3000/transfers \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: minha-primeira-tef" \
  -d '{
    "source_account_id": "SEU_ACCOUNT_ID",
    "method": "TEF",
    "amount": 10000,
    "destination": {"account_id": "ACCOUNT_ID_DA_SEGUNDA_CONTA"}
  }'
```

```
HTTP/1.1 201 Created
{"transfer_id":"a963ae06-...","method":"TEF","status":"COMPLETED","amount":10000,"fee":100,"source_account_id":"f1190d11-...","destination":{"account_id":"7b78a948-..."},"created_at":"2026-10-01T15:21:03.999865-03:00","completed_at":"2026-10-01T15:21:03.999865-03:00"}
```

Repare no `fee`: R$ 1,00 de tarifa, cobrada da origem. E rode o mesmo
comando de novo, **igualzinho**: volta `200 OK`, com o mesmo corpo, e o
dinheiro não sai outra vez. É o `Idempotency-Key`. Quem clica duas vezes
no botão de "transferir" manda o mesmo pedido duas vezes — e a chave é o
que deixa a API reconhecer a repetição. Sem o cabeçalho, a API recusa
(`QIT001015`); com a mesma chave e um valor diferente, recusa também
(`QIT001016`), porque aí não é repetição, é engano.

#### 5. Ver o extrato

```bash
curl "http://localhost:3000/accounts/SEU_ACCOUNT_ID/statement" \
  -H "INTERNAL-TOKEN: default_token"
```

```json
{"account_id":"f1190d11-...","balance":39900,"held_balance":0,"available_balance":39900,
 "items":[
  {"entry_id":5,"type":"TRANSFER_FEE","method":"TEF","amount":-100,"balance_after":39900,"reference_type":"TRANSFER","reference_id":"a963ae06-...","external_id":null,"created_at":"..."},
  {"entry_id":3,"type":"TEF_SENT","method":"TEF","amount":-10000,"balance_after":40000,"reference_type":"TRANSFER","reference_id":"a963ae06-...","external_id":null,"created_at":"..."},
  {"entry_id":2,"type":"PIX_RECEIVED","method":"PIX","amount":50000,"balance_after":50000,"reference_type":"INCOMING_TRANSFER","reference_id":"36abf9ec-...","external_id":"E0001","created_at":"..."}],
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
curl -X POST http://localhost:3000/customers \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{}'
```

```json
{"title":"Bad Request","description":"'cpf' is a required property","translation":"Payload Inválido","code":"QIT000001"}
```

**400**, e nada foi criado. Quem recusou não foi a regra de negócio: foi
o `src/schemas/`, antes da primeira linha da rota rodar. A validação para
no primeiro problema — vá preenchendo um campo de cada vez para ver a
reclamação andar.

Agora um CPF com o formato certo e os dígitos errados:

```bash
curl -X POST http://localhost:3000/customers \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{"cpf":"11122233344","name":"X","birth_date":"1990-01-01","type":"INDIVIDUAL","annual_revenue":0}'
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
curl "http://localhost:3000/accounts/SEU_ACCOUNT_ID/statement?limt=10" \
  -H "INTERNAL-TOKEN: default_token"
```

```json
{"title":"Bad Request","description":"Additional properties are not allowed ('limt' was unexpected)","translation":"Payload Inválido","code":"QIT000001"}
```

Sem essa recusa, o `limt` com a letra trocada seria ignorado e a página
viria com o tamanho padrão, como se o pedido tivesse funcionado — o pior
tipo de bug, o que não reclama.

#### Esqueceu o `-H "INTERNAL-TOKEN: ..."`?

A API responde **403** e nem chega a olhar o resto:

```json
{"title":"Forbidden","description":"Request must be internal","translation":"Requisição precisa ser interna","code":"QIT000002"}
```

#### Toda resposta vem com um número de protocolo

Repare no `-i` deste comando: ele mostra os **cabeçalhos** da resposta,
não só o corpo.

```bash
curl -i "http://localhost:3000/accounts/SEU_ACCOUNT_ID/statement?limit=1" \
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
[INFO] bootcamp-api.middlewares.request_logger [52d8e778-...] - ENTROU GET /accounts/f1190d11-.../statement?limit=1
[INFO] bootcamp-api.middlewares.request_logger [52d8e778-...] - SAIU 200 GET /accounts/f1190d11-.../statement - 7.2 ms
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
curl -i "http://localhost:3000/accounts/SEU_ACCOUNT_ID/statement?limit=1" \
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

Doze endereços respondem hoje. O contrato completo — inclusive o que
ainda vai ser construído (microcrédito, PIX e TED de saída, cartões) —
está em **`docs/api-contract.md`**.

| Método e rota | O que faz | Responde |
|---|---|---|
| `GET /` | diz qual serviço é este | `200` + nome e id |
| `GET /health_check` | diz se a API está de pé | `204`, sem corpo |
| `POST /customers` | cadastra o cliente e abre a conta | `201` + ids e status da conta |
| `GET /customers/{id}` | busca o cliente | `200` + o cliente |
| `PATCH /customers/{id}` | atualiza o faturamento (e a elegibilidade) | `200` + o cliente |
| `GET /accounts/{id}` | busca a conta, com os três saldos | `200` + a conta |
| `PATCH /accounts/{id}/status` | muda o status (`ACTIVE`, `REJECTED`, `BLOCKED`, `CLOSED`) | `200` + a conta |
| `GET /accounts/{id}/statement` | extrato, do mais novo ao mais antigo | `200` + a página |
| `GET /accounts/{id}/transfers` | transferências em que a conta é origem ou destino | `200` + a página |
| `POST /transfers` | transfere (hoje, só TEF) — exige `Idempotency-Key` | `201` (ou `200` na repetição) |
| `GET /transfers/{id}` | busca uma transferência | `200` + a transferência |
| `POST /webhooks/spi` | PIX recebido (papel do SPI) | `200`, sempre |

As dez de baixo exigem o `INTERNAL-TOKEN` (seção 6). As duas de cima
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
============================== 52 passed in 5.24s ==============================
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
> banco direto, por SQLAlchemy. Mas não para **montar** cenário — só
> para **zerar** o banco entre testes que não podem se atrapalhar. O
> cenário continua nascendo pela API, com `POST`.

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

database/
  database.sql     ← as tabelas, em SQL puro

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
  "description": "'cpf' is a required property",
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
  livre é o `QIT001021`.

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
