-- =====================================================================
-- Migracao v6 -> v7 do TITULAR (Etapa 1)
--
-- O que muda no modelo de titular:
--   v6: customer tem (cpf, cnpj, type IN ('INDIVIDUAL','MEI')). Um MEI e
--       UMA linha, com CPF e CNPJ na mesma linha e a conta pendurada nela.
--   v7: titular = um CPF OU um CNPJ (person_type NATURAL/LEGAL, document).
--       Cada MEI do v6 vira DOIS titulares:
--         - a PF  (person_type=NATURAL, document=CPF)
--         - o CNPJ(person_type=LEGAL,   document=CNPJ, legal_nature='EI',
--                  owner_customer_id -> PF, owner_person_type='NATURAL')
--       A CONTA e o ANNUAL_REVENUE do MEI ficam no CNPJ (quem factura e a
--       empresa). Saldos e ledger NAO sao tocados: so o dono da conta muda,
--       e ele continua sendo o mesmo customer_id (o do CNPJ).
--
-- PREMISSA DE ENTRADA (D5): a RENDA da PF criada na migracao e dado de
--   ENTRADA, informado pela IF ANTES da migracao, numa tabela de staging
--   `migration_pf_revenue_staging(cpf, annual_revenue)`. Se faltar a renda
--   de ALGUMA PF de MEI, a migracao ABORTA com erro claro — NUNCA assume
--   zero (zero mudaria a elegibilidade de microcredito de forma silenciosa).
--
-- PREMISSA DE ENTRADA (D6): a chave Pix do tipo CPF que estava registrada
--   na conta do MEI e PORTADA para a conta PF aberta na migracao (NAO e
--   excluida). As demais chaves (CNPJ/EMAIL/PHONE/EVP) ficam na conta do
--   CNPJ, que e a mesma conta de sempre.
--
-- IDEMPOTENTE / RE-RODAVEL: a segunda execucao NAO duplica nada. A PF e
--   detectada por document=CPF; a conta PF, por titular + tipo; a portacao
--   da chave, por ela ja apontar para a conta PF. Rodar 2x da o mesmo banco.
--
-- CONSERVACAO DE DINHEIRO: o script mede a soma de saldos e a soma do
--   ledger ANTES e DEPOIS e ABORTA se qualquer uma mudar. Nada de dinheiro
--   e criado, movido ou destruido aqui — a migracao e so de titularidade.
--
-- COMO RODAR: contra um banco com schema v7 e dados v6 ja carregados, e com
--   a tabela de staging preenchida:
--     psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f v6_to_v7_titular.sql
--   (ON_ERROR_STOP garante que um RAISE EXCEPTION derruba a transacao.)
-- =====================================================================

BEGIN;

DO $migration$
DECLARE
    balance_before   BIGINT;
    balance_after    BIGINT;
    ledger_before    BIGINT;
    ledger_after     BIGINT;
    missing_count    INTEGER;
    mei_record       RECORD;
    pf_id            UUID;
    pf_revenue       BIGINT;
    account_record   RECORD;
BEGIN
    -- ----------------------------------------------------------------
    -- 0. Fotografia do dinheiro ANTES (contas CUSTOMER + ledger inteiro)
    -- ----------------------------------------------------------------
    SELECT COALESCE(SUM(balance), 0) INTO balance_before
        FROM account WHERE type = 'CUSTOMER';
    SELECT COALESCE(SUM(amount), 0) INTO ledger_before
        FROM ledger_entry;

    -- ----------------------------------------------------------------
    -- 1. D5: toda PF de MEI precisa ter renda no staging (senao ABORTA)
    -- ----------------------------------------------------------------
    -- So checamos os MEIs que AINDA nao foram migrados (a PF deles ainda
    -- nao existe como titular NATURAL). Isso mantem a re-rodada barata.
    SELECT COUNT(*) INTO missing_count
    FROM customer c
    WHERE c.type = 'MEI'
      AND NOT EXISTS (SELECT 1 FROM customer pf
                      WHERE pf.person_type = 'NATURAL' AND pf.document = c.cpf)
      AND NOT EXISTS (SELECT 1 FROM migration_pf_revenue_staging s
                      WHERE s.cpf = c.cpf);

    IF missing_count > 0 THEN
        RAISE EXCEPTION
            'Migracao v6->v7 abortada: % PF(s) de MEI sem renda informada no staging '
            '(migration_pf_revenue_staging). D5 exige a renda da PF como dado de ENTRADA; '
            'nao assumimos zero. Preencha o staging e rode de novo.', missing_count;
    END IF;

    -- ----------------------------------------------------------------
    -- 2. Cada MEI v6 -> PF (NATURAL) + ajuste do CNPJ (LEGAL, EI)
    -- ----------------------------------------------------------------
    FOR mei_record IN
        SELECT id, cpf, cnpj, name, birth_date, is_pep, kyc_status_id
        FROM customer
        WHERE type = 'MEI'
    LOOP
        -- 2a. A PF: cria se ainda nao existe (idempotente por document=CPF).
        SELECT id INTO pf_id
        FROM customer
        WHERE person_type = 'NATURAL' AND document = mei_record.cpf;

        IF pf_id IS NULL THEN
            SELECT annual_revenue INTO pf_revenue
            FROM migration_pf_revenue_staging
            WHERE cpf = mei_record.cpf;

            INSERT INTO customer (
                person_type, document, name, birth_date, legal_nature,
                owner_customer_id, owner_person_type, annual_revenue,
                kyc_status_id, is_pep
            ) VALUES (
                'NATURAL', mei_record.cpf, mei_record.name, mei_record.birth_date, NULL,
                NULL, NULL, pf_revenue,
                mei_record.kyc_status_id, mei_record.is_pep
            )
            RETURNING id INTO pf_id;
        END IF;

        -- 2b. O CNPJ: o PROPRIO registro do MEI vira o titular LEGAL/EI.
        --     O faturamento e a conta ja estao nele; so trocamos o
        --     vocabulario (cpf/cnpj/type -> person_type/document/legal_nature)
        --     e amarramos o dono (owner_customer_id -> PF). Idempotente:
        --     se ja for LEGAL/EI apontando pra PF certa, o UPDATE e no-op.
        UPDATE customer
        SET person_type       = 'LEGAL',
            document          = mei_record.cnpj,
            legal_nature      = 'EI',
            owner_customer_id = pf_id,
            owner_person_type = 'NATURAL',
            birth_date        = NULL,       -- PJ nao tem data de nascimento
            is_pep            = FALSE,      -- is_pep so NATURAL (ck_pep_natural)
            updated_at        = now()
        WHERE id = mei_record.id
          AND person_type IS DISTINCT FROM 'LEGAL';  -- so o que falta migrar

        -- 2c. D6: porta a chave Pix CPF da conta do MEI (agora conta do CNPJ)
        --     para a conta PF. A conta PF e aberta logo abaixo (passo 3);
        --     fazemos a portacao depois dela existir, no passo 4.
    END LOOP;

    -- ----------------------------------------------------------------
    -- 3. Abre UMA conta PF (CUSTOMER, ACTIVE) para cada PF criada que
    --    ainda nao tem conta. Saldo zero: a conta PF nasce sem dinheiro
    --    (o dinheiro do MEI ficou na conta do CNPJ). Idempotente.
    -- ----------------------------------------------------------------
    FOR account_record IN
        SELECT pf.id AS pf_id
        FROM customer pf
        WHERE pf.person_type = 'NATURAL'
          AND EXISTS (SELECT 1 FROM customer ei
                      WHERE ei.legal_nature = 'EI' AND ei.owner_customer_id = pf.id)
          AND NOT EXISTS (SELECT 1 FROM account a
                          WHERE a.customer_id = pf.id AND a.type = 'CUSTOMER')
    LOOP
        INSERT INTO account (type, customer_id, branch, number, status_id, balance, held_balance)
        VALUES (
            'CUSTOMER', account_record.pf_id, '0001',
            lpad(nextval('account_number_seq')::text, 8, '0'),
            (SELECT id FROM account_status WHERE enumerator = 'ACTIVE'),
            0, 0
        );
    END LOOP;

    -- Nascimento da conta PF no historico (null -> ACTIVE), so para as
    -- contas PF que ainda nao tem evento. Idempotente.
    INSERT INTO account_status_event (account_id, from_status_id, to_status_id, reason)
    SELECT a.id, NULL,
           (SELECT id FROM account_status WHERE enumerator = 'ACTIVE'),
           'V7_MIGRATION'
    FROM account a
    JOIN customer pf ON pf.id = a.customer_id AND pf.person_type = 'NATURAL'
    WHERE a.type = 'CUSTOMER'
      AND EXISTS (SELECT 1 FROM customer ei
                  WHERE ei.legal_nature = 'EI' AND ei.owner_customer_id = pf.id)
      AND NOT EXISTS (SELECT 1 FROM account_status_event e WHERE e.account_id = a.id);

    -- ----------------------------------------------------------------
    -- 4. D6: porta a chave Pix CPF para a conta PF (NAO exclui).
    --    A chave CPF estava na conta do CNPJ (ex-MEI); passa a apontar
    --    para a conta PF. Idempotente: se ja aponta pra conta PF, no-op.
    -- ----------------------------------------------------------------
    UPDATE pix_key k
    SET account_id = pf_account.id,
        updated_at = now()
    FROM customer ei
    JOIN customer pf        ON pf.id = ei.owner_customer_id AND pf.person_type = 'NATURAL'
    JOIN account cnpj_acc   ON cnpj_acc.customer_id = ei.id   AND cnpj_acc.type = 'CUSTOMER'
    JOIN account pf_account ON pf_account.customer_id = pf.id AND pf_account.type = 'CUSTOMER'
    WHERE ei.legal_nature = 'EI'
      AND k.account_id = cnpj_acc.id
      AND k.key_type = 'CPF'
      AND k.account_id <> pf_account.id;

    -- ----------------------------------------------------------------
    -- 5. Fotografia do dinheiro DEPOIS e CONSERVACAO
    -- ----------------------------------------------------------------
    SELECT COALESCE(SUM(balance), 0) INTO balance_after
        FROM account WHERE type = 'CUSTOMER';
    SELECT COALESCE(SUM(amount), 0) INTO ledger_after
        FROM ledger_entry;

    IF balance_after <> balance_before THEN
        RAISE EXCEPTION
            'Migracao v6->v7 abortada: soma de saldos mudou (antes=%, depois=%). '
            'A migracao e so de titularidade — dinheiro nao pode mudar.',
            balance_before, balance_after;
    END IF;

    IF ledger_after <> ledger_before THEN
        RAISE EXCEPTION
            'Migracao v6->v7 abortada: soma do ledger mudou (antes=%, depois=%).',
            ledger_before, ledger_after;
    END IF;

    RAISE NOTICE 'Migracao v6->v7 OK. Soma de saldos preservada (%). Soma do ledger preservada (%).',
        balance_after, ledger_after;
END
$migration$;

COMMIT;
