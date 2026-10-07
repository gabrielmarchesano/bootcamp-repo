"""Regras que o BANCO garante sozinho, sem passar pela API.

Os testes de HTTP nunca chegam a esbarrar nelas, porque o controller
recusa antes. É justamente por isso que elas precisam de teste próprio:
são a última linha de defesa no dia em que alguém escrever um caminho
novo que esqueça a regra. Cada teste roda numa transação desfeita no fim.
"""

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.utils.db_utils import DbUtils


@pytest.fixture
def db():
    engine = create_engine(DbUtils.database_url())
    connection = engine.connect()
    transaction = connection.begin()
    yield connection
    transaction.rollback()
    connection.close()
    engine.dispose()


def refused(db, sql: str, params: dict, error=IntegrityError) -> bool:
    savepoint = db.begin_nested()
    try:
        db.execute(text(sql), params)
    except error:
        savepoint.rollback()
        return True
    savepoint.rollback()
    return False


def new_account(db, cpf: str):
    customer_id = db.execute(
        text(
            "INSERT INTO customer (person_type, document, name, birth_date, annual_revenue, kyc_status_id) "
            "VALUES ('NATURAL', :document, 'X', '1990-01-01', 100, 2) RETURNING id"
        ),
        {"document": cpf},
    ).scalar_one()
    return db.execute(
        text(
            "INSERT INTO account (type, customer_id, branch, number, status_id, balance, held_balance) "
            "VALUES ('CUSTOMER', :customer_id, '0001', :number, 3, 0, 0) RETURNING id"
        ),
        {"customer_id": customer_id, "number": cpf[-8:]},
    ).scalar_one()


def e2e(n: int) -> str:
    return f"E13370001202610051230{n:011d}"


INQUIRY = (
    "INSERT INTO pix_key_inquiry (account_id, pix_key, key_type, end_to_end_id, ispb, account_branch, account_number, "
    "account_type, owner_name, owner_masked_document, owner_person_type, expires_at) VALUES (:account, 'a@b.com', "
    "'EMAIL', :e2e, '60746948', '452', '370158', 'CHECKING', 'Fulano', '***.141.857-**', 'NATURAL', "
    "now() + interval '15 minutes') RETURNING id"
)
PIX_KEY = (
    "INSERT INTO transfer (idempotency_key, request_hash, source_account_id, method, amount, status_id, on_us, "
    "pix_transfer_type, pix_key, pix_key_inquiry_id, end_to_end_id) VALUES (:key, repeat('a', 64), :account, 'PIX', "
    "100, 3, false, 'KEY', 'a@b.com', :inquiry, :e2e)"
)


def test_e2e_from_inquiry_is_single_use_and_bound_to_the_account(db):
    a, b = new_account(db, "11111111111"), new_account(db, "22222222222")
    inquiry = db.execute(text(INQUIRY), {"account": a, "e2e": e2e(1)}).scalar_one()

    db.execute(text(PIX_KEY), {"key": str(uuid.uuid4()), "account": a, "inquiry": inquiry, "e2e": e2e(1)})

    assert refused(db, PIX_KEY, {"key": str(uuid.uuid4()), "account": a, "inquiry": inquiry, "e2e": e2e(1)})
    other = db.execute(text(INQUIRY), {"account": b, "e2e": e2e(2)}).scalar_one()
    assert refused(db, PIX_KEY, {"key": str(uuid.uuid4()), "account": a, "inquiry": other, "e2e": e2e(2)})


def test_pix_key_needs_inquiry_and_e2e_has_bcb_format(db):
    a = new_account(db, "11111111111")
    assert refused(db, PIX_KEY, {"key": str(uuid.uuid4()), "account": a, "inquiry": None, "e2e": e2e(3)})
    assert refused(db, INQUIRY, {"account": a, "e2e": "E123"})


def test_reversal_needs_original_and_reason(db):
    a = new_account(db, "11111111111")
    assert refused(
        db,
        "INSERT INTO transfer (idempotency_key, request_hash, source_account_id, method, amount, status_id, on_us, "
        "pix_transfer_type, destination_ispb, end_to_end_id) VALUES (:key, repeat('a', 64), :account, 'PIX', 10, 3, "
        "false, 'REVERSAL', '60746948', :e2e)",
        {"key": str(uuid.uuid4()), "account": a, "e2e": "D" + e2e(4)[1:]},
    )


def test_credit_card_wallet_must_belong_to_the_same_account(db):
    a, b = new_account(db, "11111111111"), new_account(db, "22222222222")
    wallet_b = db.execute(
        text(
            "INSERT INTO credit_wallet (account_id, status_id, total_limit, closing_day, due_day, "
            "monthly_interest_rate, fine_rate) VALUES (:account, 1, 1000, 5, 15, 0.08, 0.02) RETURNING id"
        ),
        {"account": b},
    ).scalar_one()

    assert refused(
        db,
        "INSERT INTO card (account_id, wallet_id, type, pan_token, last4, brand, functions, printed_name, status_id) "
        "VALUES (:account, :wallet, 'VIRTUAL', 'tok', '1234', 'VISA', 'CREDIT', 'X', 1)",
        {"account": a, "wallet": wallet_b},
    )


def test_one_live_wallet_per_account_and_fine_cap(db):
    a = new_account(db, "11111111111")
    wallet = (
        "INSERT INTO credit_wallet (account_id, status_id, total_limit, closing_day, due_day, monthly_interest_rate, "
        "fine_rate) VALUES (:account, 1, 1000, 5, 15, 0.08, :fine)"
    )
    db.execute(text(wallet), {"account": a, "fine": 0.02})

    assert refused(db, wallet, {"account": a, "fine": 0.02})
    assert refused(db, wallet, {"account": new_account(db, "22222222222"), "fine": 0.05})


def test_declined_needs_reason_and_refund_cannot_pass_capture(db):
    a = new_account(db, "11111111111")
    card = db.execute(
        text(
            "INSERT INTO card (account_id, type, pan_token, last4, brand, functions, printed_name, status_id) "
            "VALUES (:account, 'VIRTUAL', 'tok', '1234', 'VISA', 'DEBIT', 'X', 1) RETURNING id"
        ),
        {"account": a},
    ).scalar_one()
    authorization = (
        "INSERT INTO card_authorization (authorization_id, card_id, account_id, function, amount, authorized_amount, "
        "status_id, response_code, response_payload, denial_reason) VALUES (:id, :card, :account, 'DEBIT', 100, 100, "
        ":status, '00', '{}', :reason) RETURNING id"
    )

    assert refused(db, authorization, {"id": "a1", "card": card, "account": a, "status": 2, "reason": None})
    approved = db.execute(
        text(authorization), {"id": "a2", "card": card, "account": a, "status": 1, "reason": None}
    ).scalar_one()
    assert refused(
        db,
        "UPDATE card_authorization SET captured_amount = 100, refunded_amount = 101 WHERE id = :id",
        {"id": approved},
    )

    db.execute(
        text("INSERT INTO card_authorization_event (card_authorization_id, type, amount, external_id) VALUES (:id, 'CAPTURE', 100, 'c1')"),
        {"id": approved},
    )
    assert refused(
        db,
        "INSERT INTO card_authorization_event (card_authorization_id, type, amount, external_id) VALUES (:id, 'CAPTURE', 100, 'c1')",
        {"id": approved},
    )
    assert refused(db, "DELETE FROM card_authorization_event WHERE card_authorization_id = :id", {"id": approved}, DBAPIError)


def test_new_histories_and_lists_are_append_only(db):
    for table in ("pix_key_status", "credit_wallet_status", "card_status", "invoice_status"):
        assert refused(db, f"UPDATE {table} SET enumerator = enumerator || 'X' WHERE id = 1", {}, DBAPIError), table


def test_new_states_kept_old_ids(db):
    rows = db.execute(text("SELECT id, enumerator FROM card_status ORDER BY id")).all()
    assert [tuple(row) for row in rows] == [
        (1, "ACTIVE"), (2, "BLOCKED"), (3, "CANCELED"), (4, "EMBOSSING"), (5, "LOST"), (6, "STOLEN"), (7, "FRAUD"),
    ]
    assert db.execute(text("SELECT enumerator FROM transfer_status WHERE id = 8")).scalar_one() == "CANCELED"
    assert db.execute(text("SELECT enumerator FROM invoice_status WHERE id = 6")).scalar_one() == "FUTURE"