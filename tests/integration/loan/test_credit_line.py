from uuid import uuid4

from tests.conftest import ERROR_FIELDS
from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


class TestCreditLine:
    def test_put_creates_then_versions_and_same_body_is_idempotent(self):
        customer = ObjectGenerator.create_active_account()
        payload = PayloadGenerator.create_credit_line_payload(total_limit=1_000_000)

        status, first = RequestGenerator.PUT_credit_line(customer["customer_id"], payload)
        assert status == 200, first
        assert first["customer_id"] == customer["customer_id"]
        assert first["version"] == 1
        assert first["total_limit"] == 1_000_000
        assert first["available_limit"] == 1_000_000
        assert first["microcredit_balance"] == 0

        status, same = RequestGenerator.PUT_credit_line(customer["customer_id"], payload)
        assert status == 200
        assert same["version"] == 1, "mesmo corpo não cria versão nova"

        payload["monthly_interest_rate"] = 0.025
        status, changed = RequestGenerator.PUT_credit_line(customer["customer_id"], payload)
        assert status == 200
        assert changed["version"] == 2
        assert changed["credit_line_id"] == first["credit_line_id"]
        assert changed["monthly_interest_rate"] == 0.025

        status, read = RequestGenerator.GET_credit_line(customer["customer_id"])
        assert status == 200
        assert read == changed

    def test_mpo_ceilings_are_422(self):
        """Res. CMN 4.854/2020: limite ≤ R$ 21 mil, juros ≤ 4% a.m., TAC ≤ 3% — QIT001055."""
        customer = ObjectGenerator.create_active_account()

        for field, value in (
            ("total_limit", 2_100_001),
            ("monthly_interest_rate", 0.041),
            ("origination_fee_rate", 0.031),
        ):
            payload = PayloadGenerator.create_credit_line_payload()
            payload[field] = value
            status, error = RequestGenerator.PUT_credit_line(customer["customer_id"], payload)
            assert status == 422, (field, error)
            assert error["code"] == "QIT001055"
            assert set(error) == ERROR_FIELDS

        payload = PayloadGenerator.create_credit_line_payload(
            total_limit=2_100_000, monthly_interest_rate=0.04, origination_fee_rate=0.03
        )
        status, line = RequestGenerator.PUT_credit_line(customer["customer_id"], payload)
        assert status == 200, line

    def test_schema_refuses_zero_rate_and_missing_fields(self):
        customer = ObjectGenerator.create_active_account()

        status, _ = RequestGenerator.PUT_credit_line(
            customer["customer_id"], PayloadGenerator.create_credit_line_payload(monthly_interest_rate=0)
        )
        assert status == 400

        status, _ = RequestGenerator.PUT_credit_line(customer["customer_id"], {"total_limit": 1_000})
        assert status == 400

    def test_ei_uses_the_owner_line_and_cannot_have_its_own(self):
        """O EI/MEI responde com o patrimônio da PF: a linha é a dela (QIT001053 no EI)."""
        pf = ObjectGenerator.create_borrower(total_limit=1_500_000)
        ei = ObjectGenerator.create_ei(pf["customer_id"])

        status, error = RequestGenerator.PUT_credit_line(ei["customer_id"], PayloadGenerator.create_credit_line_payload())
        assert status == 422
        assert error["code"] == "QIT001053"
        assert set(error) == ERROR_FIELDS

        status, line = RequestGenerator.GET_credit_line(ei["customer_id"])
        assert status == 200
        assert line["customer_id"] == pf["customer_id"]
        assert line["total_limit"] == 1_500_000

    def test_lowering_the_limit_keeps_available_at_limit_minus_balance(self):
        borrower = ObjectGenerator.create_borrower(total_limit=2_000_000)
        ObjectGenerator.create_loan(borrower["account_id"], amount=1_200_000)

        line = ObjectGenerator.create_credit_line(borrower["customer_id"], total_limit=1_500_000)
        assert line["microcredit_balance"] == 1_200_000
        assert line["available_limit"] == 300_000

        line = ObjectGenerator.create_credit_line(borrower["customer_id"], total_limit=1_000_000)
        assert line["available_limit"] == 0, "nunca negativo"

    def test_unknown_customer_and_missing_line_are_404(self):
        status, error = RequestGenerator.PUT_credit_line(str(uuid4()), PayloadGenerator.create_credit_line_payload())
        assert status == 404
        assert error["code"] == "QIT001008"
        assert set(error) == ERROR_FIELDS

        customer = ObjectGenerator.create_active_account()
        status, error = RequestGenerator.GET_credit_line(customer["customer_id"])
        assert status == 404
        assert error["code"] == "QIT001065"
        assert set(error) == ERROR_FIELDS
