from uuid import uuid4

import sys
from os.path import abspath, dirname, join

from tests.conftest import ERROR_FIELDS
from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator

# Adiciona src ao path para carregar a constante pura (sem inicializar o banco)
src_path = abspath(join(dirname(__file__), "../../../src"))
if src_path not in sys.path:
    sys.path.append(src_path)

from constants import MPO_MAX_LIMIT


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

        # O valor exato do teto deve passar (200), assegurando que o CHECK constraint do BD 
        # (<= 2100000) está alinhado com a constante do Python.
        payload = PayloadGenerator.create_credit_line_payload(total_limit=MPO_MAX_LIMIT)
        status, _ = RequestGenerator.PUT_credit_line(customer["customer_id"], payload)
        assert status == 200, "O teto exato deve ser aceito sem erro 500 (CHECK do BD)."

        for field, value in (
            ("total_limit", MPO_MAX_LIMIT + 1),
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

    def test_payment_after_lowering_does_not_reopen_limit_above_the_new_line(self):
        """Bug 3.1: o pagamento não pode devolver limite acima do que a IF definiu.

        Linha de R$ 20 mil, contrato de R$ 15 mil, IF reduz para R$ 10 mil,
        pagamento de R$ 3 mil: o saldo (~R$ 12 mil) continua acima da linha,
        então o disponível segue 0 e um novo contrato é recusado.
        """
        borrower = ObjectGenerator.create_borrower(total_limit=2_000_000)
        loan = ObjectGenerator.create_loan(borrower["account_id"], amount=1_500_000)
        ObjectGenerator.create_credit_line(borrower["customer_id"], total_limit=1_000_000)

        status, payment = RequestGenerator.POST_loan_payment(
            loan["loan_id"], {"amount": 300_000, "mode": "REDUCE_TERM"}, str(uuid4())
        )
        assert status == 201, payment

        line = ObjectGenerator.credit_line_of(borrower["customer_id"])
        assert line["microcredit_balance"] > line["total_limit"]
        assert line["available_limit"] == 0

        status, error = RequestGenerator.POST_loan(
            borrower["account_id"], PayloadGenerator.create_loan_payload(100_000), str(uuid4())
        )
        assert status == 422
        assert error["code"] == "QIT001057"

    def test_payment_that_drops_balance_below_lowered_line_reopens_available_limit_partially(self):
        """Teste complementar do Bug 3.1: reabertura parcial do limite.

        Se a IF reduzir a linha, e os pagamentos baixarem o saldo para um valor
        menor que a nova linha, o disponível não pode ficar travado em 0,
        deve ser exatamente (nova_linha - saldo).
        """
        borrower = ObjectGenerator.create_borrower(total_limit=2_000_000)
        loan = ObjectGenerator.create_loan(borrower["account_id"], amount=1_500_000)
        ObjectGenerator.create_credit_line(borrower["customer_id"], total_limit=1_000_000)

        # O saldo é ~R$ 15 mil. O teto é R$ 10 mil. O disponível é 0.
        # Um pagamento de R$ 8 mil derruba o saldo para ~R$ 7 mil.
        # Então o disponível tem que reabrir para ~R$ 3 mil.
        status, payment = RequestGenerator.POST_loan_payment(
            loan["loan_id"], {"amount": 800_000, "mode": "REDUCE_TERM"}, str(uuid4())
        )
        assert status == 201

        line = ObjectGenerator.credit_line_of(borrower["customer_id"])
        balance = line["microcredit_balance"]
        
        assert balance < line["total_limit"], "O saldo deve ter caído abaixo da nova linha"
        assert line["available_limit"] == line["total_limit"] - balance, "O disponível não pode ficar travado em 0"

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
