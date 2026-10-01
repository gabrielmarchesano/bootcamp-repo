-- =====================================================================
-- Infra de conta digital + microcrédito — Esquema PostgreSQL (fluxos v6)
-- Bootcamp QI Tech · single-tenant (uma única IF por instalação)
--
-- Convenções
--   • Identificadores em inglês; comentários em pt-BR.
--   • Termos regulatórios brasileiros mantidos como nome próprio:
--     CPF, CNPJ, MEI, PIX, TED, TEF, SPI, STR, ISPB, KYC, PEP.
--   • Dinheiro em centavos (BIGINT). Taxas como fração (0.035 = 3,5 por cento a.m.).
--   • Timestamps em TIMESTAMPTZ; regras de negócio em America/Sao_Paulo.
--   • Enums como TEXT + CHECK (migração mais simples que ENUM nativo).
--   • Ledger imutável e em partidas dobradas (triggers no fim do arquivo).
--   • Ordem global de lock: account(s) por id → credit_line → loan
--     → installment → card → invoice.
--
-- ATENÇÃO: este arquivo NÃO pode conter o caractere de porcentagem.
-- O tests/utils/db_utils.py roda o arquivo pelo psycopg2, que trata esse
-- caractere como marcador de parâmetro — inclusive dentro de comentário.
-- =====================================================================

SET TIME ZONE 'America/Sao_Paulo';

-- ---------------------------------------------------------------------
-- 0. Apoio: calendário bancário e tabela de tarifas
-- ---------------------------------------------------------------------
CREATE TABLE holiday (
    date         DATE PRIMARY KEY,
    description  TEXT NOT NULL
);
-- Dia útil = não é sábado/domingo e não está em holiday.

CREATE TABLE fee (
    method          TEXT   NOT NULL CHECK (method IN ('TEF','PIX','TED')),
    customer_type   TEXT   NOT NULL CHECK (customer_type IN ('INDIVIDUAL','MEI')),
    amount          BIGINT NOT NULL CHECK (amount >= 0),
    effective_from  DATE   NOT NULL DEFAULT CURRENT_DATE,
    PRIMARY KEY (method, customer_type, effective_from)
);

-- ---------------------------------------------------------------------
-- 1. Cliente e conta
-- ---------------------------------------------------------------------
CREATE TABLE customer (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cpf                    CHAR(11)  NOT NULL UNIQUE,
    name                   TEXT      NOT NULL,
    birth_date             DATE      NOT NULL,
    type                   TEXT      NOT NULL CHECK (type IN ('INDIVIDUAL','MEI')),
    cnpj                   CHAR(14)  UNIQUE,
    annual_revenue         BIGINT    NOT NULL CHECK (annual_revenue >= 0),
    revenue_reference_date DATE      NOT NULL DEFAULT CURRENT_DATE,
    microcredit_eligible   BOOLEAN   NOT NULL,
    kyc_status             TEXT      NOT NULL DEFAULT 'PENDING'
                           CHECK (kyc_status IN ('PENDING','APPROVED','REJECTED')),
    is_pep                 BOOLEAN   NOT NULL DEFAULT FALSE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_mei_cnpj CHECK ((type = 'MEI') = (cnpj IS NOT NULL)),
    -- Elegibilidade: faturamento ≤ R$ 360.000,00 (defesa em profundidade)
    CONSTRAINT ck_eligibility CHECK (
        NOT microcredit_eligible OR annual_revenue <= 36000000)
);

-- Número de conta sequencial (8 dígitos), agência fixa 0001
CREATE SEQUENCE account_number_seq START 1;

CREATE TABLE account (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type             TEXT NOT NULL CHECK (type IN ('CUSTOMER','INTERNAL')),
    customer_id      UUID UNIQUE REFERENCES customer(id),
    internal_code    TEXT UNIQUE,  -- só para contas INTERNAL
    branch           CHAR(4),
    number           TEXT UNIQUE,
    status           TEXT NOT NULL DEFAULT 'REQUESTED'
                     CHECK (status IN ('REQUESTED','ACTIVE','PENDING','REJECTED',
                                       'BLOCKED','CLOSED')),
    status_reason    TEXT,
    -- saldo contábil materializado: só contas CUSTOMER (atualizado sob FOR UPDATE).
    -- Contas INTERNAL não são travadas (evita hotspot); saldo = SUM do ledger.
    balance          BIGINT,
    held_balance     BIGINT,   -- soma dos HOLDs de débito ativos
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_account_type CHECK (
        (type = 'CUSTOMER' AND customer_id IS NOT NULL AND internal_code IS NULL
             AND balance IS NOT NULL AND held_balance IS NOT NULL
             AND held_balance >= 0 AND number IS NOT NULL)
     OR (type = 'INTERNAL' AND customer_id IS NULL AND internal_code IS NOT NULL
             AND balance IS NULL AND held_balance IS NULL))
    -- Sem CHECK balance >= 0: captura mandatória de débito pode negativar (regra da IF).
);

-- ---------------------------------------------------------------------
-- 2. Ledger (partidas dobradas, imutável)
-- ---------------------------------------------------------------------
CREATE TABLE ledger_entry (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    operation_id     UUID   NOT NULL,          -- agrupa as pernas; SUM(amount) = 0
    account_id       UUID   NOT NULL REFERENCES account(id),
    amount           BIGINT NOT NULL CHECK (amount <> 0),  -- + crédito / − débito
    type             TEXT   NOT NULL CHECK (type IN (
                        'DISBURSEMENT','ORIGINATION_FEE',
                        'TEF_SENT','TEF_RECEIVED',
                        'PIX_SENT','PIX_RECEIVED',
                        'TED_SENT','TED_RECEIVED',
                        'TRANSFER_FEE',
                        'INSTALLMENT_PAYMENT',
                        'DEBIT_PURCHASE','PURCHASE_REFUND',
                        'INVOICE_PAYMENT',
                        'REVERSAL')),
    method           TEXT CHECK (method IN ('TEF','PIX','TED','CARD')),
    balance_after    BIGINT,                   -- preenchido só em conta CUSTOMER
    reference_type   TEXT CHECK (reference_type IN (
                        'TRANSFER','INCOMING_TRANSFER','LOAN',
                        'LOAN_PAYMENT','CARD_AUTHORIZATION','INVOICE_PAYMENT')),
    reference_id     UUID,
    external_id      TEXT,                     -- endToEndId / nº de controle STR
    reversal_of_id   BIGINT REFERENCES ledger_entry(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Extrato keyset: WHERE account_id = $1 AND (created_at, id) < ($2, $3) ORDER BY created_at DESC, id DESC
CREATE INDEX ix_ledger_statement ON ledger_entry (account_id, created_at DESC, id DESC);
CREATE INDEX ix_ledger_operation ON ledger_entry (operation_id);
CREATE INDEX ix_ledger_reference ON ledger_entry (reference_type, reference_id);

-- ---------------------------------------------------------------------
-- 3. Microcrédito
-- ---------------------------------------------------------------------
-- Linha vigente (1 por conta, mutável sob FOR UPDATE)
CREATE TABLE credit_line (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id              UUID NOT NULL UNIQUE REFERENCES account(id),
    version                 INT  NOT NULL DEFAULT 1 CHECK (version >= 1),
    total_limit             BIGINT NOT NULL CHECK (total_limit > 0 AND total_limit <= 2100000),
    available_limit         BIGINT NOT NULL CHECK (available_limit >= 0),
    monthly_interest_rate   NUMERIC(9,6) NOT NULL CHECK (monthly_interest_rate > 0 AND monthly_interest_rate <= 0.04),
    origination_fee_rate    NUMERIC(9,6) NOT NULL CHECK (origination_fee_rate >= 0 AND origination_fee_rate <= 0.03),  -- TAC
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_limit CHECK (available_limit <= total_limit)
);

-- Histórico append-only de cada PUT da IF (auditoria)
CREATE TABLE credit_line_version (
    credit_line_id          UUID NOT NULL REFERENCES credit_line(id),
    version                 INT  NOT NULL,
    total_limit             BIGINT NOT NULL,
    monthly_interest_rate   NUMERIC(9,6) NOT NULL,
    origination_fee_rate    NUMERIC(9,6) NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (credit_line_id, version)
);

-- Contrato de microcrédito
CREATE TABLE loan (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id                  UUID NOT NULL REFERENCES account(id),
    credit_line_id              UUID NOT NULL,
    credit_line_version         INT  NOT NULL,
    idempotency_key             TEXT NOT NULL UNIQUE,
    request_hash                CHAR(64) NOT NULL,       -- SHA-256 do payload
    principal_amount            BIGINT NOT NULL CHECK (principal_amount > 0 AND principal_amount <= 2100000),
    installment_count           SMALLINT NOT NULL CHECK (installment_count BETWEEN 2 AND 24),
    term_days                   SMALLINT NOT NULL CHECK (term_days BETWEEN 60 AND 720),
    monthly_interest_rate       NUMERIC(9,6) NOT NULL CHECK (monthly_interest_rate <= 0.04),
    effective_fee_rate          NUMERIC(9,6) NOT NULL CHECK (effective_fee_rate <= 0.03),  -- TAC proporcional
    origination_fee_amount      BIGINT NOT NULL CHECK (origination_fee_amount >= 0),
    net_amount                  BIGINT NOT NULL,
    effective_cost_monthly      NUMERIC(9,6) NOT NULL,   -- CET a.m.
    effective_cost_annual       NUMERIC(9,6) NOT NULL,   -- CET a.a.
    purpose                     TEXT NOT NULL,
    sfn_debt_declaration        BOOLEAN NOT NULL CHECK (sfn_debt_declaration),  -- teto R$ 80k no SFN
    outstanding_principal       BIGINT NOT NULL CHECK (outstanding_principal >= 0),
    status                      TEXT NOT NULL DEFAULT 'ACTIVE'
                                CHECK (status IN ('ACTIVE','PAID_OFF')),
    contracted_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_off_at                 TIMESTAMPTZ,
    FOREIGN KEY (credit_line_id, credit_line_version)
        REFERENCES credit_line_version (credit_line_id, version),
    CONSTRAINT ck_net_amount CHECK (net_amount = principal_amount - origination_fee_amount),
    CONSTRAINT ck_paid_off CHECK ((status = 'PAID_OFF') = (paid_off_at IS NOT NULL))
);
CREATE INDEX ix_loan_account_active ON loan (account_id) WHERE status = 'ACTIVE';

CREATE TABLE installment (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_id             UUID NOT NULL REFERENCES loan(id),
    number              SMALLINT NOT NULL CHECK (number >= 1),
    due_date            DATE NOT NULL,                -- já ajustado a dia útil
    principal_amount    BIGINT NOT NULL CHECK (principal_amount >= 0),
    interest_amount     BIGINT NOT NULL CHECK (interest_amount >= 0),
    total_amount        BIGINT GENERATED ALWAYS AS (principal_amount + interest_amount) STORED,
    paid_amount         BIGINT NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
    status              TEXT NOT NULL DEFAULT 'OPEN'
                        CHECK (status IN ('OPEN','PARTIAL','OVERDUE','PAID')),
    days_overdue        INT NOT NULL DEFAULT 0 CHECK (days_overdue >= 0),
    paid_at             TIMESTAMPTZ,
    UNIQUE (loan_id, number),
    CONSTRAINT ck_paid CHECK ((status = 'PAID') = (paid_at IS NOT NULL))
);
-- Filtro do job de cobrança (v6: OPEN, PARTIAL e OVERDUE)
CREATE INDEX ix_installment_collection ON installment (due_date)
    WHERE status IN ('OPEN','PARTIAL','OVERDUE');

CREATE TABLE loan_payment (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_id          UUID NOT NULL REFERENCES loan(id),
    idempotency_key  TEXT UNIQUE,         -- NULL quando source = AUTO_COLLECTION
    request_hash     CHAR(64),
    source           TEXT NOT NULL CHECK (source IN ('MANUAL','AUTO_COLLECTION')),
    mode             TEXT CHECK (mode IN ('REDUCE_TERM','REDUCE_INSTALLMENT')),
    amount           BIGINT NOT NULL CHECK (amount > 0),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_manual CHECK (
        (source = 'MANUAL' AND idempotency_key IS NOT NULL AND mode IS NOT NULL)
     OR (source = 'AUTO_COLLECTION'))
);

-- Como cada pagamento foi alocado nas parcelas (antecipação a valor presente)
CREATE TABLE payment_allocation (
    payment_id          UUID NOT NULL REFERENCES loan_payment(id),
    installment_id      UUID NOT NULL REFERENCES installment(id),
    principal_amount    BIGINT NOT NULL CHECK (principal_amount >= 0),
    interest_amount     BIGINT NOT NULL CHECK (interest_amount >= 0),
    prepayment_discount BIGINT NOT NULL DEFAULT 0 CHECK (prepayment_discount >= 0),  -- CDC art. 52 §2º
    PRIMARY KEY (payment_id, installment_id)
);

-- ---------------------------------------------------------------------
-- 4. Transferências (TEF · PIX · TED)
-- ---------------------------------------------------------------------
CREATE TABLE transfer (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key         TEXT NOT NULL UNIQUE,
    request_hash            CHAR(64) NOT NULL,
    source_account_id       UUID NOT NULL REFERENCES account(id),
    method                  TEXT NOT NULL CHECK (method IN ('TEF','PIX','TED')),
    amount                  BIGINT NOT NULL CHECK (amount > 0),
    fee                     BIGINT NOT NULL DEFAULT 0 CHECK (fee >= 0),
    status                  TEXT NOT NULL DEFAULT 'CREATED'
                            CHECK (status IN ('CREATED','SCHEDULED','SENT','COMPLETED',
                                              'REJECTED','RETURNED','FAILED')),
    on_us                   BOOLEAN NOT NULL DEFAULT FALSE,
    -- destino interno (TEF e PIX on-us)
    destination_account_id  UUID REFERENCES account(id),
    -- destino externo
    pix_key                 TEXT,
    destination_ispb        CHAR(8),
    destination_branch      TEXT,
    destination_account     TEXT,
    destination_document    TEXT,
    destination_name        TEXT,
    -- trilho
    end_to_end_id           TEXT UNIQUE,
    str_control_number      TEXT UNIQUE,
    scheduled_for           DATE,
    failure_reason          TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at            TIMESTAMPTZ,
    CONSTRAINT ck_same_account CHECK (destination_account_id IS DISTINCT FROM source_account_id),
    CONSTRAINT ck_destination_by_method CHECK (
        (method = 'TEF' AND destination_account_id IS NOT NULL AND on_us)
     OR (method = 'PIX' AND pix_key IS NOT NULL AND (on_us = (destination_account_id IS NOT NULL)))
     OR (method = 'TED' AND destination_ispb IS NOT NULL AND destination_branch IS NOT NULL
                        AND destination_account IS NOT NULL AND destination_document IS NOT NULL
                        AND NOT on_us)),
    CONSTRAINT ck_scheduled CHECK ((status = 'SCHEDULED') <= (scheduled_for IS NOT NULL))
);
-- Limite noturno: soma das saídas da conta na janela 20h–6h
CREATE INDEX ix_transfer_source_date ON transfer (source_account_id, created_at);
-- Jobs: TED agendada e reconciliação SPI/STR
CREATE INDEX ix_transfer_scheduled ON transfer (scheduled_for) WHERE status = 'SCHEDULED';
CREATE INDEX ix_transfer_sent      ON transfer (updated_at)    WHERE status = 'SENT';

-- Entradas via webhook SPI/STR (idempotência por id externo)
CREATE TABLE incoming_transfer (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rail                    TEXT NOT NULL CHECK (rail IN ('SPI','STR')),
    external_id             TEXT NOT NULL,
    destination_account_id  UUID REFERENCES account(id),
    amount                  BIGINT NOT NULL CHECK (amount > 0),
    sender_name             TEXT,
    sender_document         TEXT,
    sender_ispb             CHAR(8),
    status                  TEXT NOT NULL CHECK (status IN ('CREDITED','RETURNED')),
    received_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (rail, external_id)
);

-- ---------------------------------------------------------------------
-- 5. Cartões (débito e crédito)
-- ---------------------------------------------------------------------
CREATE TABLE card (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id          UUID NOT NULL REFERENCES account(id),
    pan_token           TEXT NOT NULL UNIQUE,     -- nunca o PAN em claro (PCI DSS)
    last4               CHAR(4) NOT NULL,
    brand               TEXT NOT NULL,
    functions           TEXT NOT NULL CHECK (functions IN ('DEBIT','CREDIT','MULTIPLE')),
    status              TEXT NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE','BLOCKED','CANCELED')),
    -- crédito (NULL se só débito)
    total_limit         BIGINT CHECK (total_limit >= 0),
    available_limit     BIGINT CHECK (available_limit >= 0),
    closing_day         SMALLINT CHECK (closing_day BETWEEN 1 AND 28),
    due_day             SMALLINT CHECK (due_day BETWEEN 1 AND 28),
    autopay             BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_credit CHECK (
        (functions = 'DEBIT' AND total_limit IS NULL)
     OR (functions <> 'DEBIT' AND total_limit IS NOT NULL AND available_limit IS NOT NULL
         AND closing_day IS NOT NULL AND due_day IS NOT NULL))
);

-- Autorização = HOLD (débito) ou reserva de limite (crédito)
CREATE TABLE card_authorization (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    authorization_id     TEXT NOT NULL UNIQUE,     -- id da rede: idempotência
    card_id              UUID NOT NULL REFERENCES card(id),
    account_id           UUID NOT NULL REFERENCES account(id),
    function             TEXT NOT NULL CHECK (function IN ('DEBIT','CREDIT')),
    amount               BIGINT NOT NULL CHECK (amount > 0),
    installment_count    SMALLINT NOT NULL DEFAULT 1 CHECK (installment_count >= 1),
    merchant_name        TEXT,
    mcc                  CHAR(4),
    status               TEXT NOT NULL CHECK (status IN (
                            'APPROVED','DECLINED','CAPTURED','EXPIRED','REVERSED','REFUNDED')),
    response_code        CHAR(2) NOT NULL,         -- '00' aprovada · '51' saldo/limite
    approval_code        CHAR(6),
    expires_at           TIMESTAMPTZ,
    response_payload     JSONB NOT NULL,           -- replay idêntico em reenvio
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Job de expiração de HOLD/reserva
CREATE INDEX ix_card_auth_expiry ON card_authorization (expires_at) WHERE status = 'APPROVED';

CREATE TABLE card_capture (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    capture_id             TEXT NOT NULL UNIQUE,
    card_authorization_id  UUID NOT NULL REFERENCES card_authorization(id),
    amount                 BIGINT NOT NULL CHECK (amount > 0),   -- pode ≠ valor autorizado
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE card_refund (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    refund_id              TEXT NOT NULL UNIQUE,
    card_authorization_id  UUID NOT NULL REFERENCES card_authorization(id),
    amount                 BIGINT NOT NULL CHECK (amount > 0),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fatura do cartão de crédito
CREATE TABLE invoice (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id                 UUID NOT NULL REFERENCES card(id),
    reference_month         DATE NOT NULL,              -- 1º dia do mês
    status                  TEXT NOT NULL DEFAULT 'OPEN'
                            CHECK (status IN ('OPEN','CLOSED','PAID','PARTIALLY_PAID','OVERDUE')),
    closing_date            DATE NOT NULL,
    due_date                DATE NOT NULL,              -- ajustada a dia útil
    total_amount            BIGINT NOT NULL DEFAULT 0,
    paid_amount             BIGINT NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
    original_debt_amount    BIGINT,                     -- base do teto do rotativo
    UNIQUE (card_id, reference_month),
    CONSTRAINT ck_dates CHECK (due_date > closing_date)
);
CREATE UNIQUE INDEX ux_invoice_open ON invoice (card_id) WHERE status = 'OPEN';
CREATE INDEX ix_invoice_closing ON invoice (closing_date) WHERE status = 'OPEN';
CREATE INDEX ix_invoice_due     ON invoice (due_date)     WHERE status IN ('CLOSED','PARTIALLY_PAID');

CREATE TABLE invoice_item (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id             UUID NOT NULL REFERENCES invoice(id),
    card_authorization_id  UUID REFERENCES card_authorization(id),
    type                   TEXT NOT NULL CHECK (type IN ('PURCHASE','PURCHASE_REFUND','REVOLVING_CHARGE')),
    amount                 BIGINT NOT NULL CHECK (amount <> 0),   -- estorno negativo
    installment_number     SMALLINT NOT NULL DEFAULT 1,
    installment_total      SMALLINT NOT NULL DEFAULT 1,
    description            TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_invoice_item ON invoice_item (invoice_id);

CREATE TABLE invoice_payment (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id       UUID NOT NULL REFERENCES invoice(id),
    idempotency_key  TEXT UNIQUE,         -- NULL no débito automático
    request_hash     CHAR(64),
    source           TEXT NOT NULL CHECK (source IN ('MANUAL','AUTOPAY')),
    amount           BIGINT NOT NULL CHECK (amount > 0),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_invoice_payment_manual CHECK (source = 'AUTOPAY' OR idempotency_key IS NOT NULL)
);
-- Débito automático: no máximo um por fatura
CREATE UNIQUE INDEX ux_invoice_payment_autopay ON invoice_payment (invoice_id) WHERE source = 'AUTOPAY';

-- ---------------------------------------------------------------------
-- 6. Eventos para a IF (transactional outbox)
-- ---------------------------------------------------------------------
CREATE TABLE outbox_event (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type            TEXT NOT NULL,   -- ACCOUNT_STATUS_CHANGED, TRANSFER_COMPLETED, INCOMING_TRANSFER_CREDITED, ...
    aggregate_type  TEXT NOT NULL,
    aggregate_id    UUID NOT NULL,
    payload         JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING','SENT','FAILED')),
    attempts        INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ
);
CREATE INDEX ix_outbox_pending ON outbox_event (id) WHERE status = 'PENDING';

-- ---------------------------------------------------------------------
-- 7. Integridade do ledger
-- ---------------------------------------------------------------------
-- 7a. Imutável: nunca UPDATE/DELETE; estorno = novo lançamento.
CREATE FUNCTION fn_immutable_ledger() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING
        MESSAGE = 'ledger_entry is immutable (post a reversal entry instead)',
        ERRCODE = 'restrict_violation';
END $$;

CREATE TRIGGER tg_immutable_ledger
    BEFORE UPDATE OR DELETE ON ledger_entry
    FOR EACH ROW EXECUTE FUNCTION fn_immutable_ledger();

-- 7b. Partidas dobradas: no COMMIT, cada operation_id soma zero.
CREATE FUNCTION fn_double_entry() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s BIGINT;
BEGIN
    SELECT COALESCE(SUM(amount), 0) INTO s FROM ledger_entry WHERE operation_id = NEW.operation_id;
    IF s <> 0 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'operation ' || NEW.operation_id || ' is unbalanced (sum = ' || s || ')',
            ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER tg_double_entry
    AFTER INSERT ON ledger_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION fn_double_entry();

-- ---------------------------------------------------------------------
-- 8. Views de apoio
-- ---------------------------------------------------------------------
-- Posição das contas internas (conciliação contra SPI, STR e bandeira)
CREATE VIEW vw_internal_account_balance AS
SELECT a.internal_code, COALESCE(SUM(l.amount), 0) AS balance
FROM account a LEFT JOIN ledger_entry l ON l.account_id = a.id
WHERE a.type = 'INTERNAL'
GROUP BY a.internal_code;

-- Saldo de microcrédito por conta (teto R$ 21 mil por instituição)
CREATE VIEW vw_microcredit_balance AS
SELECT account_id, SUM(outstanding_principal) AS microcredit_balance
FROM loan WHERE status = 'ACTIVE'
GROUP BY account_id;

-- ---------------------------------------------------------------------
-- 9. Seeds
-- ---------------------------------------------------------------------
INSERT INTO account (type, internal_code, status) VALUES
    ('INTERNAL', 'LOAN_PORTFOLIO',          'ACTIVE'),  -- carteira de crédito
    ('INTERNAL', 'ORIGINATION_FEE_REVENUE', 'ACTIVE'),  -- receita de TAC
    ('INTERNAL', 'INTEREST_REVENUE',        'ACTIVE'),  -- contrapartida dos juros
    ('INTERNAL', 'FEE_REVENUE',             'ACTIVE'),  -- receita de tarifas
    ('INTERNAL', 'SPI_SETTLEMENT',          'ACTIVE'),  -- transitória SPI
    ('INTERNAL', 'STR_SETTLEMENT',          'ACTIVE'),  -- transitória STR
    ('INTERNAL', 'CARD_SETTLEMENT',         'ACTIVE');  -- liquidação de cartão

-- Tarifas — PREMISSAS DO TIME, ajustar antes da banca:
--   • TEF R$ 1,00: o bootcamp exige tarifa na transferência; sem ela o
--     requisito não aparece na demo.
--   • PIX zero: PIX de pessoa natural é gratuito por regra do BCB.
--   • TED R$ 10,00.
INSERT INTO fee (method, customer_type, amount) VALUES
    ('TEF', 'INDIVIDUAL', 100), ('TEF', 'MEI', 100),
    ('PIX', 'INDIVIDUAL', 0),   ('PIX', 'MEI', 0),
    ('TED', 'INDIVIDUAL', 1000), ('TED', 'MEI', 1000);
