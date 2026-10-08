# Verificação final — Etapa 1: Modelo de titular v7

Branch: `etapa-1-titular-v7`
Worktree: `.worktrees/etapa-1-titular-v7`

## 1. Banco v7 do zero (docker compose)

`docker compose up -d --build` (api + db) a partir da worktree, com rede/volumes
criados do zero. Ambos os containers subiram e ficaram `healthy`:

```
etapa-1-titular-v7-api-1   Up (healthy)   0.0.0.0:3100->3000/tcp
etapa-1-titular-v7-db-1    Up (healthy)   0.0.0.0:5532->5432/tcp
```

O schema v7 carregou sem erro na inicialização do Postgres (db ficou `healthy`
pelo `pg_isready`, e a API só sobe depois disso via `depends_on: service_healthy`).

As portas 3100/5532 vêm do `.env` da worktree (`API_PORT`/`DB_PORT`), não do
padrão 3000/5432.

### Regra dura — porcentagem no `database/database.sql`

Confirmado: `database/database.sql` **NÃO contém o caractere `%`**. Varredura do
arquivo inteiro (`Get-Content -Raw` + match em `%`) retornou "NO PERCENT".

## 2. `import app` a partir de `src/`

```
python -c "import app" -> import app OK
```

Executado com o venv da worktree, a partir de `src/`. Sem erro de import.

## 3. Suíte completa (pytest)

Comando:

```
.venv\Scripts\python.exe -m pytest tests -q
```

Resultado final:

```
138 passed, 2 skipped in ~22s
```

Todos os testes executáveis passaram. Nada da Etapa 0 (Pix / TED / cartão)
regrediu — os testes de Pix, TED, cartão, ledger e schema continuam verdes.

### Os 2 skips (esperados, não são falha)

Ambos vêm de `tests/integration/transfer/test_transfer_ted.py` (linhas 39 e 57),
TED imediata. Motivo do skip:

```
TED imediata só roda na janela do STR (dia útil, 6h30–17h)
```

A verificação final rodou fora dessa janela, então os dois casos de TED imediata
foram pulados por design. É o comportamento esperado, não uma falha.

## Testes adaptados e por quê

A Etapa 1 troca o vocabulário de titular do v6 (`cpf`/`cnpj`/`type`,
`Customer.MEI`/`Customer.INDIVIDUAL`) pelo do v7 (`document` único +
`person_type` `NATURAL`/`LEGAL` + `legal_nature`). Os testes e geradores da
Etapa 0 foram migrados para esse vocabulário — sem afrouxar nenhuma asserção, só
renomeando campos/fatores para os nomes v7:

- `tests/integration/customer/test_customer_create.py` — payloads e asserções
  passam a usar `person_type`/`document`/`legal_nature`; cobre as rotas novas.
- `tests/integration/customer/test_customer_get_update.py` — GET passa a validar
  `person_type == "LEGAL"`, `document` e `legal_nature == "LTDA"` em vez de
  `cpf`/`cnpj` separados.
- `tests/integration/customer/test_customer_accounts_relationships.py` — novo
  arquivo para contas adicionais e vínculos (relacionamentos) do titular v7.
- `tests/integration/database/test_schema_rules.py` — INSERT direto no banco
  passa a usar as colunas v7 (`person_type`, `document`) em vez de
  `cpf`/`type`/colunas que não existem mais.
- `tests/integration/pix/test_pix_transfer.py`,
  `tests/integration/pix/test_pix_keys.py`,
  `tests/integration/pix/test_pix_concurrency.py` — leem `customer["document"]`
  em vez de `customer["cpf"]` (o campo exposto mudou de nome; a lógica do teste
  é a mesma).
- `tests/utils/object_generator.py`,
  `tests/utils/payload_generator.py`,
  `tests/utils/request_generator.py` — geradores passam a produzir payloads v7
  (`person_type`, `document`, naturezas jurídicas) e expõem helpers das rotas
  novas.

## Auditoria do bug do Pix — CONFIRMAÇÃO

O bug crítico do Pix manual era ler atributos de titular que não existem mais no
v7 (`holder.cpf` / `holder.cnpj` / `holder.type`, além de
`Customer.MEI` / `Customer.INDIVIDUAL`).

Auditoria em `src/`:

- **Nenhuma leitura restante** de `.cpf`, `.cnpj`, `Customer.MEI` ou
  `Customer.INDIVIDUAL` em todo o `src/`.
- A validação de titular do Pix manual
  (`src/controllers/transfer_controller.py`) agora compara
  `target["document"]` com `holder.document` — o campo único v7.
- A única ocorrência que menciona os campos antigos é um **comentário**
  (`transfer_controller.py:623`) explicando que `holder.cpf/holder.cnpj/holder.type`
  não existem mais no v7. Não é código executável.

Confirmado: o bug do Pix está corrigido e não há resquício dos atributos v6 no
código de produção.

## Veredito

Verificação final limpa. Suíte verde (138 passed, 2 skipped — os 2 skips são a
TED imediata fora da janela do STR). Pronto para o orquestrador consolidar em
`feat/backlog-v7`.
