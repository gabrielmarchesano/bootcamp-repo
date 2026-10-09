from datetime import date
from uuid import uuid4

from tests.conftest import ERROR_FIELDS
from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


def key() -> str:
    return str(uuid4())


class TestLoanSimulation:
    def test_simulation_matches_the_contract_and_writes_nothing(self):
        borrower = ObjectGenerator.create_borrower(total_limit=1_000_000)
        body = {"amount": 400_000, "installment_count": 6}

        status, simulation = RequestGenerator.POST_loan_simulation(borrower["account_id"], body)
        assert status == 200, simulation
        assert ObjectGenerator.credit_line_of(borrower["customer_id"])["available_limit"] == 1_000_000
        assert ObjectGenerator.balance_of(borrower["account_id"]) == 0

        loan = ObjectGenerator.create_loan(borrower["account_id"], 400_000, 6)
        for field in ("origination_fee_amount", "net_amount", "effective_cost_monthly", "effective_cost_annual", "term_days"):
            assert loan[field] == simulation[field], field
        assert [(item["due_date"], item["total_amount"]) for item in loan["installments"]] == [
            (item["due_date"], item["total_amount"]) for item in simulation["installments"]
        ]

    def test_price_schedule_closes_the_principal(self):
        """Price: parcela fixa, juros sobre o saldo; a última absorve o arredondamento."""
        borrower = ObjectGenerator.create_borrower(monthly_interest_rate=0.035)

        _, simulation = RequestGenerator.POST_loan_simulation(
            borrower["account_id"], {"amount": 1_000_000, "installment_count": 12}
        )
        installments = simulation["installments"]

        assert [item["number"] for item in installments] == list(range(1, 13))
        assert sum(item["principal_amount"] for item in installments) == 1_000_000
        assert installments[0]["interest_amount"] == 35_000, "1º mês: 3,5% sobre o principal inteiro"
        assert len({item["total_amount"] for item in installments[:-1]}) == 1, "parcela fixa"
        assert abs(installments[-1]["total_amount"] - installments[0]["total_amount"]) <= 12

        interests = [item["interest_amount"] for item in installments]
        assert interests == sorted(interests, reverse=True), "juros caem com o saldo"

        due_dates = [date.fromisoformat(item["due_date"]) for item in installments]
        assert due_dates == sorted(due_dates)
        assert all(day.weekday() < 5 for day in due_dates), "vencimento ajustado a dia útil"
        assert simulation["term_days"] == 360

    def test_origination_fee_is_proportional_below_120_days(self):
        """TAC proporcional abaixo de 120 dias: 3% × 60/120 = 1,5% em 2 parcelas."""
        borrower = ObjectGenerator.create_borrower(origination_fee_rate=0.03)

        _, short = RequestGenerator.POST_loan_simulation(borrower["account_id"], {"amount": 100_000, "installment_count": 2})
        _, full = RequestGenerator.POST_loan_simulation(borrower["account_id"], {"amount": 100_000, "installment_count": 4})

        assert short["effective_fee_rate"] == 0.015
        assert short["origination_fee_amount"] == 1_500
        assert short["net_amount"] == 98_500
        assert full["effective_fee_rate"] == 0.03
        assert full["origination_fee_amount"] == 3_000

    def test_cet_equals_the_rate_without_fee_and_is_higher_with_it(self):
        no_fee = ObjectGenerator.create_borrower(monthly_interest_rate=0.03, origination_fee_rate=0)
        with_fee = ObjectGenerator.create_borrower(monthly_interest_rate=0.03, origination_fee_rate=0.03)
        body = {"amount": 600_000, "installment_count": 6}

        _, plain = RequestGenerator.POST_loan_simulation(no_fee["account_id"], body)
        _, costly = RequestGenerator.POST_loan_simulation(with_fee["account_id"], body)

        assert plain["origination_fee_amount"] == 0
        assert abs(plain["effective_cost_monthly"] - 0.03) < 0.0005
        assert costly["effective_cost_monthly"] > plain["effective_cost_monthly"]
        assert abs(costly["effective_cost_annual"] - ((1 + costly["effective_cost_monthly"]) ** 12 - 1)) < 0.0001

    def test_term_and_declaration_rules(self):
        """Prazo MPO de 60 a 720 dias (2 a 24 parcelas) e declaração de dívida no SFN obrigatória."""
        borrower = ObjectGenerator.create_borrower()

        for count in (1, 25):
            status, _ = RequestGenerator.POST_loan_simulation(borrower["account_id"], {"amount": 10_000, "installment_count": count})
            assert status == 400, count

        payload = PayloadGenerator.create_loan_payload()
        payload["sfn_debt_declaration"] = False
        status, _ = RequestGenerator.POST_loan(borrower["account_id"], payload, key())
        assert status == 400

    def test_not_eligible_and_without_line_are_422(self):
        rich = ObjectGenerator.create_active_account()
        RequestGenerator.PATCH_customer(rich["customer_id"], {"annual_revenue": 36_000_001})
        ObjectGenerator.create_credit_line(rich["customer_id"])

        status, error = RequestGenerator.POST_loan_simulation(rich["account_id"], {"amount": 10_000, "installment_count": 2})
        assert status == 422
        assert error["code"] == "QIT001054"
        assert set(error) == ERROR_FIELDS

        status, error = RequestGenerator.POST_loan(rich["account_id"], PayloadGenerator.create_loan_payload(), key())
        assert status == 422
        assert error["code"] == "QIT001054"
        assert set(error) == ERROR_FIELDS

        no_line = ObjectGenerator.create_active_account()
        status, error = RequestGenerator.POST_loan(no_line["account_id"], PayloadGenerator.create_loan_payload(), key())
        assert status == 422
        assert error["code"] == "QIT001056"
        assert set(error) == ERROR_FIELDS

    def test_unknown_account_is_404(self):
        status, error = RequestGenerator.POST_loan_simulation(str(uuid4()), {"amount": 10_000, "installment_count": 2})
        assert status == 404
        assert error["code"] == "QIT001009"
        assert set(error) == ERROR_FIELDS


class TestLoanContract:
    def test_contract_disburses_net_and_posts_disbursement_and_fee(self):
        borrower = ObjectGenerator.create_borrower(initial_balance=1_000, origination_fee_rate=0.02)

        status, loan = RequestGenerator.POST_loan(borrower["account_id"], PayloadGenerator.create_loan_payload(500_000, 6), key())

        assert status == 201, loan
        assert loan["status"] == "ACTIVE"
        assert loan["principal_amount"] == 500_000
        assert loan["origination_fee_amount"] == 10_000
        assert loan["net_amount"] == 490_000
        assert loan["outstanding_principal"] == 500_000
        assert loan["customer_id"] == borrower["customer_id"]
        assert loan["exposure_customer_id"] == borrower["customer_id"]
        assert len(loan["installments"]) == 6
        assert all(item["status"] == "OPEN" and item["paid_amount"] == 0 for item in loan["installments"])

        assert ObjectGenerator.balance_of(borrower["account_id"]) == 1_000 + 490_000

        _, statement = RequestGenerator.GET_statement(borrower["account_id"])
        entries = {item["type"]: item for item in statement["items"] if item["reference_type"] == "LOAN"}
        assert entries["DISBURSEMENT"]["amount"] == 500_000
        assert entries["ORIGINATION_FEE"]["amount"] == -10_000
        assert entries["DISBURSEMENT"]["reference_id"] == loan["loan_id"]

        line = ObjectGenerator.credit_line_of(borrower["customer_id"])
        assert line["available_limit"] == 2_000_000 - 500_000
        assert line["microcredit_balance"] == 500_000

    def test_amount_above_available_limit_is_422(self):
        borrower = ObjectGenerator.create_borrower(total_limit=500_000)

        status, error = RequestGenerator.POST_loan(borrower["account_id"], PayloadGenerator.create_loan_payload(500_001), key())

        assert status == 422
        assert error["code"] == "QIT001057"
        assert set(error) == ERROR_FIELDS
        assert ObjectGenerator.balance_of(borrower["account_id"]) == 0

    def test_account_must_be_active(self):
        borrower = ObjectGenerator.create_borrower()
        RequestGenerator.PATCH_account_status(borrower["account_id"], "BLOCKED")

        status, error = RequestGenerator.POST_loan(borrower["account_id"], PayloadGenerator.create_loan_payload(), key())

        assert status == 409
        assert error["code"] == "QIT001013"
        assert set(error) == ERROR_FIELDS
        assert ObjectGenerator.credit_line_of(borrower["customer_id"])["available_limit"] == 2_000_000


class TestLoanIdempotency:
    def test_missing_or_malformed_key_is_400(self):
        borrower = ObjectGenerator.create_borrower()

        for bad in (None, "nao-e-uuid"):
            status, error = RequestGenerator.POST_loan(borrower["account_id"], PayloadGenerator.create_loan_payload(), bad)
            assert status == 400
            assert error["code"] == "QIT001015"
            assert set(error) == ERROR_FIELDS

    def test_replay_returns_the_same_loan_and_disburses_once(self):
        borrower = ObjectGenerator.create_borrower()
        payload = PayloadGenerator.create_loan_payload(200_000, 3)
        idempotency_key = key()

        status, first = RequestGenerator.POST_loan(borrower["account_id"], payload, idempotency_key)
        assert status == 201
        status, again = RequestGenerator.POST_loan(borrower["account_id"], payload, idempotency_key)
        assert status == 200
        assert again["loan_id"] == first["loan_id"]

        assert ObjectGenerator.balance_of(borrower["account_id"]) == first["net_amount"]
        _, page = RequestGenerator.GET_account_loans(borrower["account_id"])
        assert len(page["items"]) == 1

    def test_same_key_with_another_body_is_409(self):
        borrower = ObjectGenerator.create_borrower()
        idempotency_key = key()
        RequestGenerator.POST_loan(borrower["account_id"], PayloadGenerator.create_loan_payload(200_000), idempotency_key)

        status, error = RequestGenerator.POST_loan(borrower["account_id"], PayloadGenerator.create_loan_payload(200_001), idempotency_key)

        assert status == 409
        assert error["code"] == "QIT001016"
        assert set(error) == ERROR_FIELDS


class TestLoanQueries:
    def test_get_and_unknown_loan(self):
        borrower = ObjectGenerator.create_borrower()
        loan = ObjectGenerator.create_loan(borrower["account_id"])

        assert ObjectGenerator.loan_of(loan["loan_id"]) == loan

        status, error = RequestGenerator.GET_loan(str(uuid4()))
        assert status == 404
        assert error["code"] == "QIT001062"
        assert set(error) == ERROR_FIELDS

    def test_list_pages_through_cursor_and_filters_status(self):
        borrower = ObjectGenerator.create_borrower()
        created = [ObjectGenerator.create_loan(borrower["account_id"], 100_000, 2)["loan_id"] for _ in range(3)]

        seen = []
        params = {"limit": "2"}
        while True:
            status, page = RequestGenerator.GET_account_loans(borrower["account_id"], params)
            assert status == 200, page
            assert all("installments" not in item for item in page["items"])
            seen += [item["loan_id"] for item in page["items"]]
            if page["next_cursor"] is None:
                break
            params = {"limit": "2", "cursor": page["next_cursor"]}

        assert sorted(seen) == sorted(created)
        assert len(seen) == 3

        _, paid_off = RequestGenerator.GET_account_loans(borrower["account_id"], {"status": "PAID_OFF"})
        assert paid_off["items"] == []

        status, _ = RequestGenerator.GET_account_loans(borrower["account_id"], {"limit": "0"})
        assert status == 400
