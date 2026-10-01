from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


class TestWebhookSpi:
    def test_pix_received_credits_account(self):
        customer = ObjectGenerator.create_active_account()
        payload = PayloadGenerator.create_spi_received_payload(customer["account_number"], 25_000)

        status, response = RequestGenerator.POST_webhook_spi(payload)

        assert status == 200
        assert response["status"] == "CREDITED"
        assert ObjectGenerator.balance_of(customer["account_id"]) == 25_000

    def test_same_message_twice_credits_once(self):
        """O SPI pode reentregar a mesma mensagem. O crédito acontece uma vez só."""
        customer = ObjectGenerator.create_active_account()
        payload = PayloadGenerator.create_spi_received_payload(customer["account_number"], 10_000)

        status_first, first = RequestGenerator.POST_webhook_spi(payload)
        status_second, second = RequestGenerator.POST_webhook_spi(payload)

        assert status_first == 200 and status_second == 200
        assert first["incoming_transfer_id"] == second["incoming_transfer_id"]
        assert ObjectGenerator.balance_of(customer["account_id"]) == 10_000

    def test_unknown_account_is_returned_with_200(self):
        """Conta inexistente vira devolução — e o trilho recebe 200 mesmo assim.

        4xx aqui faria o SPI reenviar a mesma mensagem em loop.
        """
        payload = PayloadGenerator.create_spi_received_payload("99999999", 5_000)

        status, response = RequestGenerator.POST_webhook_spi(payload)

        assert status == 200
        assert response["status"] == "RETURNED"

    def test_blocked_account_still_receives_but_closed_does_not(self):
        blocked = ObjectGenerator.create_active_account()
        RequestGenerator.PATCH_account_status(blocked["account_id"], "BLOCKED")

        closed = ObjectGenerator.create_active_account()
        RequestGenerator.PATCH_account_status(closed["account_id"], "CLOSED")

        _, to_blocked = RequestGenerator.POST_webhook_spi(
            PayloadGenerator.create_spi_received_payload(blocked["account_number"], 1_000)
        )
        _, to_closed = RequestGenerator.POST_webhook_spi(
            PayloadGenerator.create_spi_received_payload(closed["account_number"], 1_000)
        )

        assert to_blocked["status"] == "CREDITED"
        assert to_closed["status"] == "RETURNED"
        assert ObjectGenerator.balance_of(closed["account_id"]) == 0
