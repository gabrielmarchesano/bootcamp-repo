-- =====================================================================
-- Staging da migracao v6 -> v7 (D5): renda das PF de MEI
--
-- A renda da pessoa fisica criada na migracao e dado de ENTRADA,
-- informado pela IF ANTES de rodar a migracao. Este arquivo cria a
-- tabela de staging; a IF a preenche (uma linha por CPF de MEI) antes
-- de rodar o 01_v6_to_v7_titular.sql.
--
-- Se faltar a renda de alguma PF, a migracao ABORTA (nao assume zero).
-- A tabela e temporaria por natureza: pode ser dropada depois que a
-- migracao concluir com sucesso.
-- =====================================================================

CREATE TABLE IF NOT EXISTS migration_pf_revenue_staging (
    cpf             VARCHAR(14) PRIMARY KEY CHECK (cpf ~ '^[0-9]{11}$'),
    annual_revenue  BIGINT NOT NULL CHECK (annual_revenue >= 0)  -- centavos
);

-- Exemplo de preenchimento (a IF substitui pelos dados reais):
--   INSERT INTO migration_pf_revenue_staging (cpf, annual_revenue) VALUES
--       ('12345678901', 5000000),
--       ('98765432100', 12000000);
