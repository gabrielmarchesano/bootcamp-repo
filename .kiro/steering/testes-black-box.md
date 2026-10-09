# Testes: só black box

Os testes deste repositório são **black box**: tratam a API como caixa-preta, mandam HTTP de verdade para a API de pé e conferem só o que volta (status e corpo).

- **Não escrever testes unitários.** Nada de testar uma função de `src/` direto no Python, nem para cálculo (Price, TAC, CET): a conta é provada pela resposta da API (ex.: `POST /account/{key}/loan/simulation`).
- **Regra de ouro:** o teste não importa nada de `src/`. Se importar, deixou de ser black box.
- **Não ler o banco para conferir resultado.** A asserção vem da API (GET do recurso, extrato, resposta do job). Se não dá para provar pela API, diga isso, em vez de consultar tabela.
- A única exceção é **montar cenário que depende do calendário** (vencer parcela, passar o fechamento de fatura, expirar autorização), via `DbUtils.execute` e sempre dentro de um helper nomeado em `tests/utils/object_generator.py`. Os testes não chamam SQL direto.
- Erros: confira o `code` e o formato do base-service com `assert set(error) == ERROR_FIELDS` (`tests/conftest.py`).
- Requisições via `RequestGenerator`, payloads via `PayloadGenerator`, cenários via `ObjectGenerator` (`tests/utils/`).
