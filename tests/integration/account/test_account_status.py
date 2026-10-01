from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


class TestAccountStatus:
    def test_get_account_exposes_balances(self):
        customer = ObjectGenerator.create_active_account()

        status, account = RequestGenerator.GET_account(customer["account_id"])

        assert status == 200
        assert account["balance"] == 0
        assert account["held_balance"] == 0
        assert account["available_balance"] == 0
        assert account["status"] == "ACTIVE"

    def test_pending_can_be_approved(self):
        payload = PayloadGenerator.create_customer_payload(is_pep=True)
        _, customer = RequestGenerator.POST_customer(payload)
        assert customer["status"] == "PENDING"

        status, account = RequestGenerator.PATCH_account_status(customer["account_id"], "ACTIVE", "PEP aprovado")

        assert status == 200
        assert account["status"] == "ACTIVE"
        assert account["status_reason"] == "PEP aprovado"

    def test_block_and_unblock(self):
        customer = ObjectGenerator.create_active_account()

        status, account = RequestGenerator.PATCH_account_status(customer["account_id"], "BLOCKED")
        assert status == 200
        assert account["status"] == "BLOCKED"

        status, account = RequestGenerator.PATCH_account_status(customer["account_id"], "ACTIVE")
        assert status == 200
        assert account["status"] == "ACTIVE"

    def test_invalid_transitions_are_409(self):
        """ACTIVE não volta para REJECTED, e REJECTED não tem saída nenhuma."""
        active = ObjectGenerator.create_active_account()
        status, response = RequestGenerator.PATCH_account_status(active["account_id"], "REJECTED")
        assert status == 409
        assert response["code"] == "QIT001012"

        status, response = RequestGenerator.PATCH_account_status(active["account_id"], "ACTIVE")
        assert status == 409, "ACTIVE → ACTIVE não é transição"

    def test_close_requires_zero_balance(self):
        customer = ObjectGenerator.create_active_account(initial_balance=1)

        status, response = RequestGenerator.PATCH_account_status(customer["account_id"], "CLOSED")

        assert status == 409
        assert response["code"] == "QIT001014"

    def test_closed_is_final(self):
        customer = ObjectGenerator.create_active_account()

        status, _ = RequestGenerator.PATCH_account_status(customer["account_id"], "CLOSED")
        assert status == 200

        for new_status in ("ACTIVE", "BLOCKED"):
            status, response = RequestGenerator.PATCH_account_status(customer["account_id"], new_status)
            assert status == 409
            assert response["code"] == "QIT001012"

    def test_reason_is_mandatory(self):
        customer = ObjectGenerator.create_active_account()

        status, response = RequestGenerator.PATCH_account_status(customer["account_id"], "BLOCKED", reason="")

        assert status == 400
        assert response["code"] == "QIT000001"
