from uuid import uuid4

from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator
from tests.integration.pix.test_pix_keys import unique_email


def key() -> str:
    return str(uuid4())


class TestPixByKey:
    def test_on_us_pix_by_key_completes_now_with_201(self):
        payer = ObjectGenerator.create_active_account(initial_balance=50_000)
        receiver = ObjectGenerator.create_active_account()
        email = unique_email()
        ObjectGenerator.own_pix_key(receiver["account_id"], email)

        inquiry = ObjectGenerator.lookup(email, payer["account_id"])
        payload = PayloadGenerator.create_pix_key_payload(email, inquiry["end_to_end_id"], 10_000, "aluguel")
        status, transfer = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, key())

        assert status == 201, transfer
        assert transfer["status"] == "COMPLETED"
        assert transfer["pix"]["pix_transfer_type"] == "KEY"
        assert transfer["pix"]["end_to_end_id"] == inquiry["end_to_end_id"]
        assert ObjectGenerator.balance_of(payer["account_id"]) == 40_000
        assert ObjectGenerator.balance_of(receiver["account_id"]) == 10_000

    def test_external_pix_by_key_is_202_sent_and_settles_by_webhook(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        inquiry = ObjectGenerator.lookup("fornecedor@externo.com", payer["account_id"])
        payload = PayloadGenerator.create_pix_key_payload("fornecedor@externo.com", inquiry["end_to_end_id"], 5_000)

        status, transfer = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, key())
        assert status == 202, transfer
        assert transfer["status"] == "SENT"
        assert ObjectGenerator.balance_of(payer["account_id"]) == 15_000

        status, settled = RequestGenerator.POST_webhook_spi(
            PayloadGenerator.create_spi_event_payload("SETTLED", inquiry["end_to_end_id"])
        )
        assert status == 200
        assert settled["status"] == "COMPLETED"

        status, again = RequestGenerator.POST_webhook_spi(
            PayloadGenerator.create_spi_event_payload("SETTLED", inquiry["end_to_end_id"])
        )
        assert status == 200 and again["status"] == "COMPLETED"

    def test_rejected_pix_returns_the_money_and_keeps_the_rail_code(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        inquiry = ObjectGenerator.lookup("fornecedor@externo.com", payer["account_id"])
        payload = PayloadGenerator.create_pix_key_payload("fornecedor@externo.com", inquiry["end_to_end_id"], 7_000)
        _, transfer = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, key())

        status, rejected = RequestGenerator.POST_webhook_spi(
            PayloadGenerator.create_spi_event_payload("REJECTED", inquiry["end_to_end_id"], "PXT000132")
        )

        assert status == 200
        assert rejected["status"] == "REJECTED"
        assert rejected["failure"]["code"] == "PXT000132"
        assert ObjectGenerator.balance_of(payer["account_id"]) == 20_000

        _, statement = RequestGenerator.GET_statement(payer["account_id"])
        assert statement["items"][0]["type"] == "REVERSAL"

    def test_e2e_is_single_use(self):
        """QI: o end_to_end_id vale para UMA transferência, tenha dado certo ou não."""
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        inquiry = ObjectGenerator.lookup("fornecedor@externo.com", payer["account_id"])
        payload = PayloadGenerator.create_pix_key_payload("fornecedor@externo.com", inquiry["end_to_end_id"], 1_000)

        status_first, _ = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, key())
        status_second, error = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, key())

        assert status_first == 202
        assert status_second == 409
        assert error["code"] == "QIT001022"

    def test_e2e_from_another_accounts_inquiry_is_refused(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        someone_else = ObjectGenerator.create_active_account()
        inquiry = ObjectGenerator.lookup("fornecedor@externo.com", someone_else["account_id"])
        payload = PayloadGenerator.create_pix_key_payload("fornecedor@externo.com", inquiry["end_to_end_id"], 1_000)

        status, error = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, key())

        assert status == 404
        assert error["code"] == "QIT001036"

    def test_key_must_match_the_inquiry(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        inquiry = ObjectGenerator.lookup("fornecedor@externo.com", payer["account_id"])
        payload = PayloadGenerator.create_pix_key_payload("+5511988887777", inquiry["end_to_end_id"], 1_000)

        status, error = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, key())

        assert status == 422
        assert error["code"] == "QIT001037"

    def test_replay_returns_200_and_moves_money_once(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        inquiry = ObjectGenerator.lookup("fornecedor@externo.com", payer["account_id"])
        payload = PayloadGenerator.create_pix_key_payload("fornecedor@externo.com", inquiry["end_to_end_id"], 3_000)
        idempotency_key = key()

        status_first, first = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, idempotency_key)
        status_second, second = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, idempotency_key)

        assert (status_first, status_second) == (202, 200)
        assert first["transfer_id"] == second["transfer_id"]
        assert second["request_control_key"] == idempotency_key
        assert ObjectGenerator.balance_of(payer["account_id"]) == 17_000

    def test_emoji_in_message_is_refused(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        inquiry = ObjectGenerator.lookup("fornecedor@externo.com", payer["account_id"])
        payload = PayloadGenerator.create_pix_key_payload(
            "fornecedor@externo.com", inquiry["end_to_end_id"], 1_000, "valeu \U0001F600"
        )

        status, error = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, key())

        assert status == 422
        assert error["code"] == "QIT001024"

    def test_idempotency_key_must_be_uuid_v4(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        payload = PayloadGenerator.create_pix_manual_payload(1_000)

        status, error = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, "nao-sou-uuid-v4")

        assert status == 400
        assert error["code"] == "QIT001015"


class TestPixManual:
    def test_external_manual_pix(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)

        status, transfer = RequestGenerator.POST_pix_transfer(
            payer["account_id"], PayloadGenerator.create_pix_manual_payload(2_500), key()
        )

        assert status == 202, transfer
        assert transfer["pix"]["pix_transfer_type"] == "MANUAL"
        assert transfer["pix"]["end_to_end_id"].startswith("E13370001")
        assert transfer["destination"]["account_type"] == "CHECKING"

    def test_on_us_manual_pix_needs_the_holders_document(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        receiver = ObjectGenerator.create_active_account()
        _, receiver_customer = RequestGenerator.GET_customer(receiver["customer_id"])

        target = PayloadGenerator.target_account(ispb="13370001", document="52998224725")
        target.update(branch="0001", number=receiver["account_number"])
        status, error = RequestGenerator.POST_pix_transfer(
            payer["account_id"], PayloadGenerator.create_pix_manual_payload(1_000, target), key()
        )
        assert status == 422
        assert error["code"] == "QIT001042"

        target["document"] = receiver_customer["document"]
        status, transfer = RequestGenerator.POST_pix_transfer(
            payer["account_id"], PayloadGenerator.create_pix_manual_payload(1_000, target), key()
        )
        assert status == 201, transfer
        assert ObjectGenerator.balance_of(receiver["account_id"]) == 1_000

    def test_insufficient_balance(self):
        payer = ObjectGenerator.create_active_account(initial_balance=500)

        status, error = RequestGenerator.POST_pix_transfer(
            payer["account_id"], PayloadGenerator.create_pix_manual_payload(1_000), key()
        )

        assert status == 422
        assert error["code"] == "QIT001017"

    def test_schema_refuses_key_fields_on_manual(self):
        payer = ObjectGenerator.create_active_account(initial_balance=500)
        payload = PayloadGenerator.create_pix_manual_payload(100)
        payload["pix_key"] = "fornecedor@externo.com"

        status, error = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, key())

        assert status == 400
        assert error["code"] == "QIT000001"