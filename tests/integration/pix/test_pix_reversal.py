from uuid import uuid4

from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


def key() -> str:
    return str(uuid4())


def receive_pix(account_number: str, amount: int) -> dict:
    status, incoming = RequestGenerator.POST_webhook_spi(PayloadGenerator.create_spi_received_payload(account_number, amount))
    assert status == 200 and incoming["status"] == "CREDITED", incoming
    return incoming


class TestPixReversal:
    def test_partial_reversals_up_to_the_received_amount(self):
        customer = ObjectGenerator.create_active_account()
        incoming = receive_pix(customer["account_number"], 10_000)

        status, first = RequestGenerator.POST_pix_reversal(
            customer["account_id"], incoming["incoming_transfer_id"], {"amount": 6_000, "reversal_reason": "CLIENT_REQUEST"}, key()
        )
        assert status == 202, first
        assert first["pix"]["pix_transfer_type"] == "REVERSAL"
        assert first["pix"]["end_to_end_id"].startswith("D")
        assert ObjectGenerator.balance_of(customer["account_id"]) == 4_000

        status, error = RequestGenerator.POST_pix_reversal(
            customer["account_id"], incoming["incoming_transfer_id"], {"amount": 4_001, "reversal_reason": "CLIENT_REQUEST"}, key()
        )
        assert status == 422
        assert error["code"] == "QIT001026"

        status, rest = RequestGenerator.POST_pix_reversal(
            customer["account_id"], incoming["incoming_transfer_id"], {"amount": 4_000, "reversal_reason": "RECONCILIATION"}, key()
        )
        assert status == 202, rest
        assert ObjectGenerator.balance_of(customer["account_id"]) == 0

    def test_rejected_reversal_frees_the_ceiling_again(self):
        customer = ObjectGenerator.create_active_account()
        incoming = receive_pix(customer["account_number"], 5_000)

        _, reversal = RequestGenerator.POST_pix_reversal(
            customer["account_id"], incoming["incoming_transfer_id"], {"amount": 5_000, "reversal_reason": "CLIENT_REQUEST"}, key()
        )
        RequestGenerator.POST_webhook_spi(
            PayloadGenerator.create_spi_event_payload("REJECTED", reversal["pix"]["end_to_end_id"], "PXT000134")
        )
        assert ObjectGenerator.balance_of(customer["account_id"]) == 5_000

        status, again = RequestGenerator.POST_pix_reversal(
            customer["account_id"], incoming["incoming_transfer_id"], {"amount": 5_000, "reversal_reason": "CLIENT_REQUEST"}, key()
        )
        assert status == 202, again

    def test_only_the_receiving_account_can_reverse(self):
        customer = ObjectGenerator.create_active_account()
        intruder = ObjectGenerator.create_active_account(initial_balance=10_000)
        incoming = receive_pix(customer["account_number"], 5_000)

        status, error = RequestGenerator.POST_pix_reversal(
            intruder["account_id"], incoming["incoming_transfer_id"], {"amount": 100, "reversal_reason": "CLIENT_REQUEST"}, key()
        )

        assert status == 404
        assert error["code"] == "QIT001038"

    def test_returned_incoming_cannot_be_reversed(self):
        closed = ObjectGenerator.create_active_account()
        RequestGenerator.PATCH_account_status(closed["account_id"], "CLOSED")
        _, incoming = RequestGenerator.POST_webhook_spi(
            PayloadGenerator.create_spi_received_payload(closed["account_number"], 1_000)
        )
        assert incoming["status"] == "RETURNED"

        status, error = RequestGenerator.POST_pix_reversal(
            closed["account_id"], incoming["incoming_transfer_id"], {"amount": 100, "reversal_reason": "CLIENT_REQUEST"}, key()
        )
        assert status == 409
        assert error["code"] == "QIT001013"


class TestReversalReceived:
    def test_reversal_of_our_pix_credits_the_payer(self):
        """Devolução recebida (QI: incoming_pix do tipo reversal) aponta para o NOSSO Pix."""
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        inquiry = ObjectGenerator.lookup("fornecedor@externo.com", payer["account_id"])
        RequestGenerator.POST_pix_transfer(
            payer["account_id"],
            PayloadGenerator.create_pix_key_payload("fornecedor@externo.com", inquiry["end_to_end_id"], 8_000),
            key(),
        )
        RequestGenerator.POST_webhook_spi(PayloadGenerator.create_spi_event_payload("SETTLED", inquiry["end_to_end_id"]))

        reversal = PayloadGenerator.create_spi_received_payload(payer["account_number"], 3_000)
        reversal.update(pix_transfer_type="REVERSAL", original_end_to_end_id=inquiry["end_to_end_id"])
        status, incoming = RequestGenerator.POST_webhook_spi(reversal)

        assert status == 200
        assert incoming["status"] == "CREDITED"
        assert incoming["pix_transfer_type"] == "REVERSAL"
        assert incoming["original_transfer_id"] is not None
        assert ObjectGenerator.balance_of(payer["account_id"]) == 15_000

    def test_reversal_above_the_original_goes_back(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        inquiry = ObjectGenerator.lookup("fornecedor@externo.com", payer["account_id"])
        RequestGenerator.POST_pix_transfer(
            payer["account_id"],
            PayloadGenerator.create_pix_key_payload("fornecedor@externo.com", inquiry["end_to_end_id"], 2_000),
            key(),
        )
        RequestGenerator.POST_webhook_spi(PayloadGenerator.create_spi_event_payload("SETTLED", inquiry["end_to_end_id"]))

        reversal = PayloadGenerator.create_spi_received_payload(payer["account_number"], 2_001)
        reversal.update(pix_transfer_type="REVERSAL", original_end_to_end_id=inquiry["end_to_end_id"])
        status, incoming = RequestGenerator.POST_webhook_spi(reversal)

        assert status == 200
        assert incoming["status"] == "RETURNED"
        assert ObjectGenerator.balance_of(payer["account_id"]) == 18_000

    def test_webhook_accepts_unknown_fields(self):
        """QI: webhook não deve ser mapeado de forma restritiva."""
        customer = ObjectGenerator.create_active_account()
        payload = PayloadGenerator.create_spi_received_payload(customer["account_number"], 100)
        payload["campo_novo_do_trilho"] = {"qualquer": "coisa"}

        status, incoming = RequestGenerator.POST_webhook_spi(payload)

        assert status == 200
        assert incoming["status"] == "CREDITED"
