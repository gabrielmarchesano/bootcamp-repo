from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


class TestCreditWallet:
    def test_create_and_get(self):
        customer = ObjectGenerator.create_active_account()

        wallet = ObjectGenerator.create_credit_wallet(customer["account_id"], total_limit=300_000)

        assert wallet["status"] == "ACTIVE"
        assert wallet["available_limit"] == 300_000
        assert wallet["status_events"][0]["from_status"] is None

        status, fetched = RequestGenerator.GET_credit_wallet(wallet["wallet_id"])
        assert status == 200 and fetched["wallet_id"] == wallet["wallet_id"]

    def test_one_live_wallet_per_account(self):
        """QI CIN000043: carteira ativa já existe."""
        customer = ObjectGenerator.create_active_account()
        ObjectGenerator.create_credit_wallet(customer["account_id"])

        status, error = RequestGenerator.POST_credit_wallet(
            customer["account_id"], PayloadGenerator.create_credit_wallet_payload()
        )

        assert status == 409
        assert error["code"] == "QIT001030"

    def test_fine_above_two_percent_is_refused_by_schema(self):
        customer = ObjectGenerator.create_active_account()
        payload = PayloadGenerator.create_credit_wallet_payload()
        payload["fine_rate"] = 0.05

        status, error = RequestGenerator.POST_credit_wallet(customer["account_id"], payload)

        assert status == 400
        assert error["code"] == "QIT000001"

    def test_wallet_needs_active_account(self):
        customer = ObjectGenerator.create_active_account()
        RequestGenerator.PATCH_account_status(customer["account_id"], "BLOCKED")

        status, error = RequestGenerator.POST_credit_wallet(
            customer["account_id"], PayloadGenerator.create_credit_wallet_payload()
        )

        assert status == 409
        assert error["code"] == "QIT001013"

    def test_limit_cannot_go_below_used(self):
        """QI CIN000110."""
        customer = ObjectGenerator.create_active_account()
        wallet = ObjectGenerator.create_credit_wallet(customer["account_id"], total_limit=100_000)
        card = ObjectGenerator.create_card(customer["account_id"])
        RequestGenerator.POST_card_authorization(PayloadGenerator.create_authorization_payload(card["card_id"], 60_000))

        status, error = RequestGenerator.PATCH_credit_wallet_limit(wallet["wallet_id"], 50_000)
        assert status == 422
        assert error["code"] == "QIT001031"

        status, updated = RequestGenerator.PATCH_credit_wallet_limit(wallet["wallet_id"], 60_000)
        assert status == 200
        assert updated["available_limit"] == 0

    def test_status_machine(self):
        customer = ObjectGenerator.create_active_account()
        wallet = ObjectGenerator.create_credit_wallet(customer["account_id"])

        assert RequestGenerator.PATCH_credit_wallet_status(wallet["wallet_id"], "BLOCKED")[0] == 200
        assert RequestGenerator.PATCH_credit_wallet_status(wallet["wallet_id"], "ACTIVE")[0] == 200
        status, closed = RequestGenerator.PATCH_credit_wallet_status(wallet["wallet_id"], "CLOSED")
        assert status == 200
        assert [e["to_status"] for e in closed["status_events"]] == ["ACTIVE", "BLOCKED", "ACTIVE", "CLOSED"]

        status, error = RequestGenerator.PATCH_credit_wallet_status(wallet["wallet_id"], "ACTIVE")
        assert status == 409
        assert error["code"] == "QIT001032"

        # fechada, a conta pode abrir outra
        status, _ = RequestGenerator.POST_credit_wallet(customer["account_id"], PayloadGenerator.create_credit_wallet_payload())
        assert status == 201

    def test_wallet_with_used_limit_cannot_close(self):
        customer = ObjectGenerator.create_active_account()
        wallet = ObjectGenerator.create_credit_wallet(customer["account_id"])
        card = ObjectGenerator.create_card(customer["account_id"])
        RequestGenerator.POST_card_authorization(PayloadGenerator.create_authorization_payload(card["card_id"], 1_000))

        status, error = RequestGenerator.PATCH_credit_wallet_status(wallet["wallet_id"], "CLOSED")

        assert status == 409
        assert error["code"] == "QIT001032"