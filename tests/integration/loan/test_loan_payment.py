import re
from uuid import uuid4

from tests.conftest import ERROR_FIELDS
from tests.utils import ObjectGenerator, RequestGenerator


def key() -> str:
    return str(uuid4())


def pay(loan_id: str, amount: int, mode: str = "REDUCE_TERM", idempotency_key: str = None):
    return RequestGenerator.POST_loan_payment(loan_id, {"amount": amount, "mode": mode}, idempotency_key or key())


def payoff_amount(loan_id: str) -> int:
    """Quanto quita o contrato hoje. A API não expõe esse número fora do erro QIT001059."""
    status, error = pay(loan_id, 100_000_000_000)
    assert status == 422 and error["code"] == "QIT001059", error
    return int(re.search(r"amount due (\d+)", error["description"]).group(1))


def contracted(amount: int = 600_000, installment_count: int = 6, initial_balance: int = 200_000, **line_terms):
    borrower = ObjectGenerator.create_borrower(initial_balance=initial_balance, **line_terms)
    loan = ObjectGenerator.create_loan(borrower["account_id"], amount, installment_count)
    return borrower, loan


class TestLoanPayment:
    def test_reduce_term_prepays_from_the_last_installment_with_discount(self):
        borrower, loan = contracted()
        last = loan["installments"][-1]

        status, payment = pay(loan["loan_id"], last["total_amount"])

        assert status == 201, payment
        assert payment["source"] == "MANUAL"
        assert payment["mode"] == "REDUCE_TERM"
        numbers = [item["number"] for item in payment["allocations"]]
        assert numbers[-1] == 6 and set(numbers) <= {5, 6}
        assert sum(item["prepayment_discount"] for item in payment["allocations"]) > 0, "CDC art. 52 §2º"

        after = {item["number"]: item for item in payment["loan"]["installments"]}
        assert after[6]["status"] == "PAID"
        assert after[1]["paid_amount"] == 0, "as primeiras ficam intactas"

    def test_reduce_installment_spreads_over_every_future_installment(self):
        borrower, loan = contracted()

        status, payment = pay(loan["loan_id"], 120_000, "REDUCE_INSTALLMENT")

        assert status == 201, payment
        assert [item["number"] for item in payment["allocations"]] == [1, 2, 3, 4, 5, 6]
        assert sum(item["principal_amount"] + item["interest_amount"] for item in payment["allocations"]) == 120_000
        after = payment["loan"]["installments"]
        assert len(after) == 6, "o prazo não muda"
        assert all(item["status"] == "PARTIAL" for item in after)
        assert all(0 < item["remaining_amount"] < item["total_amount"] for item in after)

    def test_cash_goes_out_of_the_account_and_only_principal_returns_to_the_limit(self):
        """Premissa D1 da RFC: o teto conta só o principal em aberto — juros não ocupam limite."""
        borrower, loan = contracted(total_limit=2_000_000)
        balance_before = ObjectGenerator.balance_of(borrower["account_id"])
        line_before = ObjectGenerator.credit_line_of(borrower["customer_id"])

        _, payment = pay(loan["loan_id"], 150_000)

        principal = sum(item["principal_amount"] for item in payment["allocations"])
        interest = sum(item["interest_amount"] for item in payment["allocations"])
        assert principal + interest == 150_000
        assert ObjectGenerator.balance_of(borrower["account_id"]) == balance_before - 150_000

        line_after = ObjectGenerator.credit_line_of(borrower["customer_id"])
        assert line_after["available_limit"] == line_before["available_limit"] + principal
        assert line_after["microcredit_balance"] == 600_000 - principal
        assert payment["loan"]["outstanding_principal"] == 600_000 - principal

        _, statement = RequestGenerator.GET_statement(borrower["account_id"])
        entry = next(item for item in statement["items"] if item["type"] == "INSTALLMENT_PAYMENT")
        assert entry["amount"] == -150_000
        assert entry["reference_type"] == "LOAN_PAYMENT"
        assert entry["reference_id"] == payment["payment_id"]

    def test_overdue_installment_is_paid_first_and_in_full(self):
        borrower, loan = contracted()
        ObjectGenerator.make_installments_due(loan["loan_id"], [1], days_ago=5)
        first = loan["installments"][0]

        _, payment = pay(loan["loan_id"], first["total_amount"] + 10_000, "REDUCE_TERM")

        by_number = {item["number"]: item for item in payment["allocations"]}
        assert by_number[1]["principal_amount"] + by_number[1]["interest_amount"] == first["total_amount"]
        assert by_number[1]["prepayment_discount"] == 0, "vencida não tem desconto"
        assert 6 in by_number, "a sobra antecipa a última"

    def test_payoff_closes_the_contract_and_frees_the_whole_line(self):
        borrower, loan = contracted(total_limit=2_000_000)
        payoff = payoff_amount(loan["loan_id"])
        assert payoff < sum(item["total_amount"] for item in loan["installments"]), "quitação antecipada tem desconto"

        status, payment = pay(loan["loan_id"], payoff)

        assert status == 201, payment
        assert payment["loan"]["status"] == "PAID_OFF"
        assert payment["loan"]["outstanding_principal"] == 0
        assert payment["loan"]["paid_off_at"] is not None
        assert all(item["status"] == "PAID" for item in payment["loan"]["installments"])
        assert ObjectGenerator.credit_line_of(borrower["customer_id"])["available_limit"] == 2_000_000

        status, error = pay(loan["loan_id"], 1)
        assert status == 409
        assert error["code"] == "QIT001063"
        assert set(error) == ERROR_FIELDS

        _, page = RequestGenerator.GET_account_loans(borrower["account_id"], {"status": "PAID_OFF"})
        assert [item["loan_id"] for item in page["items"]] == [loan["loan_id"]]

    def test_amount_above_due_and_insufficient_balance_are_422(self):
        borrower, loan = contracted(initial_balance=0)
        payoff = payoff_amount(loan["loan_id"])

        status, error = pay(loan["loan_id"], payoff + 1)
        assert status == 422
        assert error["code"] == "QIT001059"
        assert set(error) == ERROR_FIELDS

        # Sem saldo inicial, a conta tem só o líquido do desembolso — menos que a quitação.
        assert ObjectGenerator.balance_of(borrower["account_id"]) < payoff
        status, error = pay(loan["loan_id"], payoff)
        assert status == 422
        assert error["code"] == "QIT001017"
        assert set(error) == ERROR_FIELDS
        assert ObjectGenerator.loan_of(loan["loan_id"])["outstanding_principal"] == 600_000

    def test_idempotency(self):
        borrower, loan = contracted()
        idempotency_key = key()

        status, error = RequestGenerator.POST_loan_payment(loan["loan_id"], {"amount": 1_000, "mode": "REDUCE_TERM"})
        assert status == 400
        assert error["code"] == "QIT001015"
        assert set(error) == ERROR_FIELDS

        status, first = pay(loan["loan_id"], 50_000, idempotency_key=idempotency_key)
        assert status == 201
        status, again = pay(loan["loan_id"], 50_000, idempotency_key=idempotency_key)
        assert status == 200
        assert again["payment_id"] == first["payment_id"]
        assert ObjectGenerator.balance_of(borrower["account_id"]) == 200_000 + loan["net_amount"] - 50_000

        status, error = pay(loan["loan_id"], 50_001, idempotency_key=idempotency_key)
        assert status == 409
        assert error["code"] == "QIT001016"
        assert set(error) == ERROR_FIELDS

    def test_schema_and_unknown_loan(self):
        borrower, loan = contracted()

        status, _ = RequestGenerator.POST_loan_payment(loan["loan_id"], {"amount": 1_000, "mode": "OTHER"}, key())
        assert status == 400

        status, error = pay(str(uuid4()), 1_000)
        assert status == 404
        assert error["code"] == "QIT001062"
        assert set(error) == ERROR_FIELDS
