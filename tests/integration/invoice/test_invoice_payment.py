from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from tests.conftest import ERROR_FIELDS
from tests.utils import ObjectGenerator, RequestGenerator


def key() -> str:
    return str(uuid4())


def setup_invoice(purchase: int = 30_000, initial_balance: int = 100_000, total_limit: int = 100_000):
    """Conta com saldo, carteira, cartão e uma compra no crédito na fatura OPEN."""
    customer = ObjectGenerator.create_active_account(initial_balance=initial_balance)
    wallet = ObjectGenerator.create_credit_wallet(customer["account_id"], total_limit=total_limit)
    card = ObjectGenerator.create_card(customer["account_id"])
    ObjectGenerator.create_credit_purchase(card["card_id"], purchase)
    invoice = ObjectGenerator.open_invoice_of(wallet["wallet_id"])
    return customer, wallet, card, invoice


def used_limit(wallet_id: str) -> int:
    _, wallet = RequestGenerator.GET_credit_wallet(wallet_id)
    return wallet["used_limit"]


def close(invoice_id: str) -> dict:
    ObjectGenerator.move_invoice_dates(invoice_id, closing_days_ago=1, due_in_days=7)
    ObjectGenerator.run_job("close_invoices")
    return ObjectGenerator.invoice_of(invoice_id)


class TestInvoicePayment:
    def test_paying_an_open_invoice_is_an_advance_and_frees_the_limit(self):
        customer, wallet, _, invoice = setup_invoice(purchase=30_000)
        assert used_limit(wallet["wallet_id"]) == 30_000

        status, payment = RequestGenerator.POST_invoice_payment(invoice["invoice_id"], {"amount": 10_000}, key())

        assert status == 201, payment
        assert payment["source"] == "MANUAL"
        assert payment["status"] == "OPEN", "antes do fechamento o status não muda"
        assert payment["paid_amount"] == 10_000
        assert payment["remaining_amount"] == 20_000
        assert used_limit(wallet["wallet_id"]) == 20_000
        assert ObjectGenerator.balance_of(customer["account_id"]) == 90_000

        _, statement = RequestGenerator.GET_statement(customer["account_id"])
        entry = next(item for item in statement["items"] if item["type"] == "INVOICE_PAYMENT")
        assert entry["amount"] == -10_000
        assert entry["reference_id"] == payment["payment_id"]

    def test_closed_invoice_goes_partially_paid_then_paid(self):
        customer, wallet, _, invoice = setup_invoice(purchase=30_000)
        assert close(invoice["invoice_id"])["status"] == "CLOSED"

        _, partial = RequestGenerator.POST_invoice_payment(invoice["invoice_id"], {"amount": 12_000}, key())
        assert partial["status"] == "PARTIALLY_PAID"

        _, paid = RequestGenerator.POST_invoice_payment(invoice["invoice_id"], {"amount": 18_000}, key())
        assert paid["status"] == "PAID"
        assert paid["remaining_amount"] == 0
        assert used_limit(wallet["wallet_id"]) == 0

        status, error = RequestGenerator.POST_invoice_payment(invoice["invoice_id"], {"amount": 1}, key())
        assert status == 409
        assert error["code"] == "QIT001064"
        assert set(error) == ERROR_FIELDS

    def test_above_outstanding_and_without_balance_are_422(self):
        customer, wallet, _, invoice = setup_invoice(purchase=30_000, initial_balance=5_000)

        status, error = RequestGenerator.POST_invoice_payment(invoice["invoice_id"], {"amount": 30_001}, key())
        assert status == 422
        assert error["code"] == "QIT001060"
        assert set(error) == ERROR_FIELDS

        status, error = RequestGenerator.POST_invoice_payment(invoice["invoice_id"], {"amount": 6_000}, key())
        assert status == 422
        assert error["code"] == "QIT001017"
        assert set(error) == ERROR_FIELDS
        assert ObjectGenerator.invoice_of(invoice["invoice_id"])["paid_amount"] == 0

    def test_idempotency(self):
        customer, wallet, _, invoice = setup_invoice()
        idempotency_key = key()

        status, error = RequestGenerator.POST_invoice_payment(invoice["invoice_id"], {"amount": 1_000})
        assert status == 400
        assert error["code"] == "QIT001015"
        assert set(error) == ERROR_FIELDS

        status, first = RequestGenerator.POST_invoice_payment(invoice["invoice_id"], {"amount": 5_000}, idempotency_key)
        assert status == 201
        status, again = RequestGenerator.POST_invoice_payment(invoice["invoice_id"], {"amount": 5_000}, idempotency_key)
        assert status == 200
        assert again["payment_id"] == first["payment_id"]
        assert ObjectGenerator.balance_of(customer["account_id"]) == 95_000

        status, error = RequestGenerator.POST_invoice_payment(invoice["invoice_id"], {"amount": 5_001}, idempotency_key)
        assert status == 409
        assert error["code"] == "QIT001016"
        assert set(error) == ERROR_FIELDS

    def test_parallel_payments_never_pass_the_invoice(self):
        customer, wallet, _, invoice = setup_invoice(purchase=30_000)

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(
                pool.map(
                    lambda _: RequestGenerator.POST_invoice_payment(invoice["invoice_id"], {"amount": 10_000}, key()),
                    range(6),
                )
            )

        statuses = [status for status, _ in results]
        assert statuses.count(201) == 3, results
        assert ObjectGenerator.invoice_of(invoice["invoice_id"])["paid_amount"] == 30_000
        assert ObjectGenerator.balance_of(customer["account_id"]) == 70_000

    def test_unknown_invoice_is_404(self):
        status, error = RequestGenerator.POST_invoice_payment(str(uuid4()), {"amount": 1_000}, key())
        assert status == 404
        assert error["code"] == "QIT001048"
        assert set(error) == ERROR_FIELDS


class TestInvoiceCharge:
    def test_charge_lands_on_the_overdue_invoice_up_to_the_original_debt(self):
        """Lei 14.690/2023: encargos acumulados não passam de 100% da dívida original (QIT001061)."""
        customer = ObjectGenerator.create_active_account()
        wallet = ObjectGenerator.create_credit_wallet(customer["account_id"], total_limit=100_000)
        card = ObjectGenerator.create_card(customer["account_id"])
        invoice = ObjectGenerator.overdue_invoice(card["card_id"], wallet["wallet_id"], 20_000)
        assert invoice["original_debt_amount"] == 20_000

        status, charged = RequestGenerator.POST_invoice_charge(
            invoice["invoice_id"], {"type": "REVOLVING", "amount": 15_000}, key()
        )
        assert status == 201, charged
        assert charged["total_amount"] == 35_000
        assert charged["charge"]["amount"] == 15_000
        assert any(item["type"] == "REVOLVING_CHARGE" for item in charged["items"])
        assert used_limit(wallet["wallet_id"]) == 35_000

        status, error = RequestGenerator.POST_invoice_charge(
            invoice["invoice_id"], {"type": "INSTALLMENT_PLAN", "amount": 5_001}, key()
        )
        assert status == 422
        assert error["code"] == "QIT001061"
        assert set(error) == ERROR_FIELDS

        status, _ = RequestGenerator.POST_invoice_charge(
            invoice["invoice_id"], {"type": "INSTALLMENT_PLAN", "amount": 5_000}, key()
        )
        assert status == 201
        assert ObjectGenerator.invoice_of(invoice["invoice_id"])["total_amount"] == 40_000

    def test_only_overdue_invoices_take_charges(self):
        _, _, _, invoice = setup_invoice()

        status, error = RequestGenerator.POST_invoice_charge(invoice["invoice_id"], {"type": "REVOLVING", "amount": 100}, key())

        assert status == 409
        assert error["code"] == "QIT001066"
        assert set(error) == ERROR_FIELDS

    def test_charge_idempotency_and_schema(self):
        customer = ObjectGenerator.create_active_account()
        wallet = ObjectGenerator.create_credit_wallet(customer["account_id"])
        card = ObjectGenerator.create_card(customer["account_id"])
        invoice = ObjectGenerator.overdue_invoice(card["card_id"], wallet["wallet_id"], 20_000)
        body = {"type": "REVOLVING", "amount": 1_000}
        idempotency_key = key()

        status, first = RequestGenerator.POST_invoice_charge(invoice["invoice_id"], body, idempotency_key)
        assert status == 201
        status, again = RequestGenerator.POST_invoice_charge(invoice["invoice_id"], body, idempotency_key)
        assert status == 200
        assert again["charge"]["invoice_item_id"] == first["charge"]["invoice_item_id"]
        assert ObjectGenerator.invoice_of(invoice["invoice_id"])["total_amount"] == 21_000

        status, error = RequestGenerator.POST_invoice_charge(invoice["invoice_id"], {"type": "REVOLVING", "amount": 1_001}, idempotency_key)
        assert status == 409
        assert error["code"] == "QIT001016"
        assert set(error) == ERROR_FIELDS

        status, _ = RequestGenerator.POST_invoice_charge(invoice["invoice_id"], {"type": "FINE", "amount": 1}, key())
        assert status == 400
