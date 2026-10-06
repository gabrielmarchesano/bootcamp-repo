from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


def run_parallel(function, jobs, workers: int = 8):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(function, jobs))


class TestPixConcurrency:
    def test_same_e2e_in_parallel_moves_money_once(self):
        """Oito pedidos com chaves de idempotência diferentes e o MESMO e2e."""
        payer = ObjectGenerator.create_active_account(initial_balance=50_000)
        inquiry = ObjectGenerator.lookup("fornecedor@externo.com", payer["account_id"])
        payload = PayloadGenerator.create_pix_key_payload("fornecedor@externo.com", inquiry["end_to_end_id"], 1_000)

        results = run_parallel(
            lambda _: RequestGenerator.POST_pix_transfer(payer["account_id"], payload, str(uuid4())), range(8)
        )

        statuses = sorted(status for status, _ in results)
        assert statuses == [202] + [409] * 7, statuses
        assert ObjectGenerator.balance_of(payer["account_id"]) == 49_000

    def test_parallel_reversals_never_pass_the_received_amount(self):
        customer = ObjectGenerator.create_active_account()
        _, incoming = RequestGenerator.POST_webhook_spi(
            PayloadGenerator.create_spi_received_payload(customer["account_number"], 10_000)
        )

        results = run_parallel(
            lambda _: RequestGenerator.POST_pix_reversal(
                customer["account_id"],
                incoming["incoming_transfer_id"],
                {"amount": 3_000, "reversal_reason": "CLIENT_REQUEST"},
                str(uuid4()),
            ),
            range(6),
        )

        statuses = [status for status, _ in results]
        assert statuses.count(202) == 3, statuses
        assert statuses.count(422) == 3, statuses
        assert ObjectGenerator.balance_of(customer["account_id"]) == 1_000

    def test_crossed_on_us_manual_pix_do_not_deadlock(self):
        a = ObjectGenerator.create_active_account(initial_balance=20_000)
        b = ObjectGenerator.create_active_account(initial_balance=20_000)
        documents = {}
        for account in (a, b):
            _, customer = RequestGenerator.GET_customer(account["customer_id"])
            documents[account["account_id"]] = customer["cpf"]

        def target_of(account):
            target = PayloadGenerator.target_account(ispb="13370001", document=documents[account["account_id"]])
            target.update(branch="0001", number=account["account_number"])
            return target

        jobs = [(a, b)] * 10 + [(b, a)] * 10
        results = run_parallel(
            lambda job: RequestGenerator.POST_pix_transfer(
                job[0]["account_id"], PayloadGenerator.create_pix_manual_payload(500, target_of(job[1])), str(uuid4())
            ),
            jobs,
            workers=12,
        )

        assert [status for status, _ in results].count(201) == 20
        assert ObjectGenerator.balance_of(a["account_id"]) + ObjectGenerator.balance_of(b["account_id"]) == 40_000