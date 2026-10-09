from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


class TestCardIssuing:
    def test_debit_card_needs_no_wallet(self):
        customer = ObjectGenerator.create_active_account()

        card = ObjectGenerator.create_card(customer["account_id"], functions="DEBIT")

        assert card["wallet_id"] is None
        assert card["status"] == "ACTIVE"
        assert len(card["last4"]) == 4

    def test_credit_card_needs_active_wallet(self):
        customer = ObjectGenerator.create_active_account()

        status, error = RequestGenerator.POST_card(customer["account_id"], PayloadGenerator.create_card_payload(functions="CREDIT"))
        assert status == 422
        assert error["code"] == "QIT001045"

        wallet = ObjectGenerator.create_credit_wallet(customer["account_id"])
        card = ObjectGenerator.create_card(customer["account_id"], functions="CREDIT")
        assert card["wallet_id"] == wallet["wallet_id"]

    def test_virtual_and_plastic_share_the_same_wallet(self):
        """QI: uma carteira = uma fatura. Os dois cartões consomem o MESMO limite."""
        customer = ObjectGenerator.create_active_account()
        wallet = ObjectGenerator.create_credit_wallet(customer["account_id"], total_limit=10_000)
        virtual = ObjectGenerator.create_card(customer["account_id"])
        plastic = ObjectGenerator.create_card(customer["account_id"], card_type="PLASTIC")
        RequestGenerator.PATCH_card_activate(plastic["card_id"], plastic["activation_code"])

        _, first = RequestGenerator.POST_card_authorization(PayloadGenerator.create_authorization_payload(virtual["card_id"], 7_000))
        _, second = RequestGenerator.POST_card_authorization(PayloadGenerator.create_authorization_payload(plastic["card_id"], 4_000))

        assert virtual["wallet_id"] == plastic["wallet_id"] == wallet["wallet_id"]
        assert first["status"] == "APPROVED"
        assert second["status"] == "DECLINED"
        assert second["denial_reason"] == "INSUFFICIENT_LIMIT"

    def test_plastic_is_born_embossing_and_activates_with_code(self):
        customer = ObjectGenerator.create_active_account()
        plastic = ObjectGenerator.create_card(customer["account_id"], card_type="PLASTIC", functions="DEBIT")
        assert plastic["status"] == "EMBOSSING"
        assert plastic["contactless_enabled"] is True

        wrong = "000000" if plastic["activation_code"] != "000000" else "111111"
        status, error = RequestGenerator.PATCH_card_activate(plastic["card_id"], wrong)
        assert status == 422
        assert error["code"] == "QIT001033"

        status, active = RequestGenerator.PATCH_card_activate(plastic["card_id"], plastic["activation_code"])
        assert status == 200
        assert active["status"] == "ACTIVE"
        assert [e["to_status"] for e in active["status_events"]] == ["EMBOSSING", "ACTIVE"]

        status, error = RequestGenerator.PATCH_card_activate(plastic["card_id"], plastic["activation_code"])
        assert status == 409

    def test_virtual_card_cannot_be_activated_by_code(self):
        customer = ObjectGenerator.create_active_account()
        virtual = ObjectGenerator.create_card(customer["account_id"], functions="DEBIT")

        status, error = RequestGenerator.PATCH_card_activate(virtual["card_id"], "123456")

        assert status == 422
        assert error["code"] == "QIT001034"

    def test_embossing_cannot_be_activated_by_status_patch(self):
        customer = ObjectGenerator.create_active_account()
        plastic = ObjectGenerator.create_card(customer["account_id"], card_type="PLASTIC", functions="DEBIT")

        status, error = RequestGenerator.PATCH_card_status(plastic["card_id"], "ACTIVE")

        assert status == 409
        assert error["code"] == "QIT001032"

    def test_lost_is_terminal(self):
        customer = ObjectGenerator.create_active_account()
        card = ObjectGenerator.create_card(customer["account_id"], functions="DEBIT")

        assert RequestGenerator.PATCH_card_status(card["card_id"], "BLOCKED")[0] == 200
        assert RequestGenerator.PATCH_card_status(card["card_id"], "ACTIVE")[0] == 200
        assert RequestGenerator.PATCH_card_status(card["card_id"], "LOST", "perdido no metrô")[0] == 200

        status, error = RequestGenerator.PATCH_card_status(card["card_id"], "ACTIVE")
        assert status == 409
        assert error["code"] == "QIT001032"

    def test_card_for_inactive_account_is_409(self):
        customer = ObjectGenerator.create_active_account()
        RequestGenerator.PATCH_account_status(customer["account_id"], "BLOCKED")

        status, error = RequestGenerator.POST_card(customer["account_id"], PayloadGenerator.create_card_payload(functions="DEBIT"))

        assert status == 409
        assert error["code"] == "QIT001013"

    def test_virtual_with_contactless_is_refused_by_schema(self):
        customer = ObjectGenerator.create_active_account()
        payload = PayloadGenerator.create_card_payload(functions="DEBIT")
        payload["contactless_enabled"] = True

        status, error = RequestGenerator.POST_card(customer["account_id"], payload)

        assert status == 400
