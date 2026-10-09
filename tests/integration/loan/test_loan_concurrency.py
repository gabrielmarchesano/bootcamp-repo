from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


def key() -> str:
    return str(uuid4())


class TestLoanConcurrency:
    def test_pf_and_its_mei_share_the_ceiling_under_parallel_contracts(self):
        """O teto é do PATRIMÔNIO: a conta da PF e a do MEI disputam a mesma linha.

        Pedidos simultâneos pelas duas contas nunca somam mais que o limite —
        o lock da linha serializa e o segundo lê o limite já reduzido.
        """
        pf = ObjectGenerator.create_borrower(total_limit=2_100_000)
        mei = ObjectGenerator.create_ei(pf["customer_id"])
        accounts = [pf["account_id"], mei["account_id"]] * 4

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(
                    lambda account_id: RequestGenerator.POST_loan(
                        account_id, PayloadGenerator.create_loan_payload(800_000, 4), key()
                    ),
                    accounts,
                )
            )

        statuses = [status for status, _ in results]
        assert statuses.count(201) == 2, results
        assert all(body["code"] == "QIT001057" for status, body in results if status != 201), results

        line = ObjectGenerator.credit_line_of(pf["customer_id"])
        assert line["microcredit_balance"] == 1_600_000
        assert line["available_limit"] == 500_000

        _, pf_loans = RequestGenerator.GET_account_loans(pf["account_id"])
        _, mei_loans = RequestGenerator.GET_account_loans(mei["account_id"])
        borrowed = pf_loans["items"] + mei_loans["items"]
        assert len(borrowed) == 2
        assert {loan["exposure_customer_id"] for loan in borrowed} == {pf["customer_id"]}

    def test_ltda_of_a_partner_has_its_own_ceiling(self):
        """Premissa D2 da RFC: sociedade (LTDA/SLU) tem teto próprio, separado do sócio PF."""
        pf = ObjectGenerator.create_borrower(total_limit=500_000)
        ltda = ObjectGenerator.create_borrower(person_type="LEGAL", total_limit=500_000)
        status, _ = RequestGenerator.POST_customer_relationship(
            ltda["customer_id"], {"natural_customer_id": pf["customer_id"], "role": "PARTNER"}
        )
        assert status == 201

        ObjectGenerator.create_loan(pf["account_id"], 500_000, 2)
        loan = ObjectGenerator.create_loan(ltda["account_id"], 500_000, 2)

        assert loan["exposure_customer_id"] == ltda["customer_id"]
        assert ObjectGenerator.credit_line_of(pf["customer_id"])["available_limit"] == 0
        assert ObjectGenerator.credit_line_of(ltda["customer_id"])["available_limit"] == 0

    def test_same_key_in_parallel_contracts_once(self):
        borrower = ObjectGenerator.create_borrower()
        payload = PayloadGenerator.create_loan_payload(300_000, 3)
        idempotency_key = key()

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(
                pool.map(lambda _: RequestGenerator.POST_loan(borrower["account_id"], payload, idempotency_key), range(6))
            )

        assert sorted(status for status, _ in results) == [200] * 5 + [201], results
        assert len({body["loan_id"] for _, body in results}) == 1
        assert ObjectGenerator.balance_of(borrower["account_id"]) == results[0][1]["net_amount"]
        assert ObjectGenerator.credit_line_of(borrower["customer_id"])["microcredit_balance"] == 300_000

    def test_parallel_prepayments_never_pay_more_than_the_payoff(self):
        borrower = ObjectGenerator.create_borrower(initial_balance=2_000_000)
        loan = ObjectGenerator.create_loan(borrower["account_id"], 600_000, 6)
        balance_before = ObjectGenerator.balance_of(borrower["account_id"])
        # ~40% da quitação: cabem dois, o terceiro passaria do saldo devedor.
        amount = 240_000

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(
                pool.map(
                    lambda _: RequestGenerator.POST_loan_payment(
                        loan["loan_id"], {"amount": amount, "mode": "REDUCE_TERM"}, key()
                    ),
                    range(6),
                )
            )

        statuses = [status for status, _ in results]
        assert statuses.count(201) == 2, results
        assert all(body["code"] == "QIT001059" for status, body in results if status != 201), results
        assert ObjectGenerator.balance_of(borrower["account_id"]) == balance_before - 2 * amount

        after = ObjectGenerator.loan_of(loan["loan_id"])
        assert after["status"] == "ACTIVE"
        assert after["outstanding_principal"] > 0
