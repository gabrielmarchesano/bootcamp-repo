from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


class TestCardConcurrency:
    def test_parallel_authorizations_never_pass_the_limit(self):
        customer = ObjectGenerator.create_active_account()
        wallet = ObjectGenerator.create_credit_wallet(customer["account_id"], total_limit=10_000)
        card = ObjectGenerator.create_card(customer["account_id"])

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(
                pool.map(
                    lambda _: RequestGenerator.POST_card_authorization(
                        PayloadGenerator.create_authorization_payload(card["card_id"], 2_000)
                    ),
                    range(10),
                )
            )

        decisions = [body["status"] for _, body in results]
        assert decisions.count("APPROVED") == 5, decisions
        _, after = RequestGenerator.GET_credit_wallet(wallet["wallet_id"])
        assert after["used_limit"] == 10_000

    def test_same_capture_in_parallel_counts_once(self):
        customer = ObjectGenerator.create_active_account(initial_balance=10_000)
        card = ObjectGenerator.create_card(customer["account_id"], functions="DEBIT")
        payload = PayloadGenerator.create_authorization_payload(card["card_id"], 4_000, function="DEBIT")
        RequestGenerator.POST_card_authorization(payload)
        capture = {"capture_id": f"cap-{uuid4().hex[:10]}", "authorization_id": payload["authorization_id"], "amount": 4_000}

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: RequestGenerator.POST_card_capture(capture), range(6)))

        assert all(status == 200 for status, _ in results), results
        assert ObjectGenerator.balance_of(customer["account_id"]) == 6_000
        _, authorization = RequestGenerator.GET_card_authorization(payload["authorization_id"])
        assert authorization["captured_amount"] == 4_000