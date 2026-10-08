# Migração v6 → v7 do titular (Etapa 1)

Transforma dados do modelo de titular v6 (um `customer` com `cpf`, `cnpj`,
`type IN ('INDIVIDUAL','MEI')`) para o v7 (`person_type`, `document`,
`legal_nature`, `owner_customer_id`). Só mexe em **titularidade** — nenhum
centavo é criado, movido ou destruído.

## O que acontece com cada MEI do v6

Cada MEI (uma linha v6 com CPF e CNPJ) vira **dois** titulares no v7:

- a **PF** — `person_type=NATURAL`, `document=CPF`, com uma conta nova ACTIVE
  de saldo zero;
- o **CNPJ** — `person_type=LEGAL`, `document=CNPJ`, `legal_nature='EI'`,
  `owner_customer_id` apontando para a PF. **A conta e o `annual_revenue` do
  MEI continuam no CNPJ** (quem fatura é a empresa).

INDIVIDUAL do v6 vira PF (NATURAL) direto; esse caso é tratado à parte do
loop de MEI (o script acima foca no desdobramento do MEI, que é o único que
cria um segundo titular).

## Decisões de entrada

- **D5 — renda da PF é dado de ENTRADA (staging).** A IF informa a renda de
  cada PF de MEI *antes* da migração, na tabela
  `migration_pf_revenue_staging`. Se faltar a renda de alguma PF, a migração
  **aborta** com erro claro — nunca assume zero.
- **D6 — chave Pix CPF é PORTADA.** A chave Pix do tipo CPF que estava na
  conta do MEI passa a apontar para a conta PF aberta na migração. Ela **não
  é excluída**. As demais chaves ficam na conta do CNPJ (que é a mesma conta
  de antes).

## Garantias

- **Idempotente / re-rodável.** Rodar o script 2× produz o mesmo banco: a PF
  é detectada por `document=CPF`, a conta PF por titular+tipo, a portação da
  chave por ela já apontar para a conta PF.
- **Conservação de dinheiro.** O script mede a soma de saldos (contas
  CUSTOMER) e a soma do ledger antes e depois e **aborta** se qualquer uma
  mudar.

## Como rodar

```sh
# 1. cria a tabela de staging
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 00_staging_pf_revenue.sql

# 2. a IF preenche a renda de cada PF de MEI (ver exemplo no 00_...sql)

# 3. roda a migração (idempotente, com conservação de dinheiro)
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 01_v6_to_v7_titular.sql
```

`ON_ERROR_STOP=1` garante que um `RAISE EXCEPTION` derruba a transação
inteira (a migração roda dentro de um `BEGIN/COMMIT`).
