from datetime import datetime
from uuid import uuid4

import pytest

from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator

# Tarifa de TEF do seed (database/database.sql). Se o time mudar o seed,
# este número muda junto.
TEF_FEE = 100
NIGHT_LIMIT = 100_000


def new_key() -> str:
    return str(uuid4())


class TestTransferTef:
    def test_tef_moves_money_and_charges_fee(self):
        source = ObjectGenerator.create_active_account(initial_balance=50_000)
        destination = ObjectGenerator.create_active_account()

        payload = PayloadGenerator.create_tef_payload(source["account_id"], destination["account_id"], 10_000)
        status, transfer = RequestGenerator.POST_transfer(payload, new_key())

        assert status == 201
        assert transfer["status"] == "COMPLETED"
        assert transfer["fee"] == TEF_FEE
        assert ObjectGenerator.balance_of(source["account_id"]) == 50_000 - 10_000 - TEF_FEE
        assert ObjectGenerator.balance_of(destination["account_id"]) == 10_000

    def test_tef_appears_in_both_statements(self):
        source = ObjectGenerator.create_active_account(initial_balance=5_000)
        destination = ObjectGenerator.create_active_account()

        payload = PayloadGenerator.create_tef_payload(source["account_id"], destination["account_id"], 1_000)
        _, transfer = RequestGenerator.POST_transfer(payload, new_key())

        _, source_statement = RequestGenerator.GET_statement(source["account_id"])
        _, destination_statement = RequestGenerator.GET_statement(destination["account_id"])

        source_types = [item["type"] for item in source_statement["items"]]
        assert source_types[:2] == ["TRANSFER_FEE", "TEF_SENT"]
        assert destination_statement["items"][0]["type"] == "TEF_RECEIVED"
        assert destination_statement["items"][0]["reference_id"] == transfer["transfer_id"]

    def test_missing_or_malformed_idempotency_key_is_400(self):
        source = ObjectGenerator.create_active_account(initial_balance=5_000)
        destination = ObjectGenerator.create_active_account()
        payload = PayloadGenerator.create_tef_payload(source["account_id"], destination["account_id"], 1_000)

        for key in (None, "curta", "tem espaço no meio"):
            status, response = RequestGenerator.POST_transfer(payload, key)
            assert status == 400, key
            assert response["code"] == "QIT001015"

        assert ObjectGenerator.balance_of(source["account_id"]) == 5_000

    def test_replay_returns_original_without_moving_money_again(self):
        """O clique duplo: mesma chave, mesmo corpo. 201 na primeira, 200 na segunda, débito uma vez."""
        source = ObjectGenerator.create_active_account(initial_balance=20_000)
        destination = ObjectGenerator.create_active_account()
        payload = PayloadGenerator.create_tef_payload(source["account_id"], destination["account_id"], 5_000)
        key = new_key()

        status_first, first = RequestGenerator.POST_transfer(payload, key)
        status_second, second = RequestGenerator.POST_transfer(payload, key)

        assert status_first == 201
        assert status_second == 200
        assert first == second
        assert ObjectGenerator.balance_of(source["account_id"]) == 20_000 - 5_000 - TEF_FEE

    def test_same_key_with_different_payload_is_409(self):
        source = ObjectGenerator.create_active_account(initial_balance=20_000)
        destination = ObjectGenerator.create_active_account()
        key = new_key()

        first = PayloadGenerator.create_tef_payload(source["account_id"], destination["account_id"], 1_000)
        second = PayloadGenerator.create_tef_payload(source["account_id"], destination["account_id"], 2_000)

        status, _ = RequestGenerator.POST_transfer(first, key)
        assert status == 201

        status, response = RequestGenerator.POST_transfer(second, key)
        assert status == 409
        assert response["code"] == "QIT001016"

    def test_insufficient_balance_counts_the_fee(self):
        """Saldo de 1.000 não paga TEF de 1.000: falta a tarifa."""
        source = ObjectGenerator.create_active_account(initial_balance=1_000)
        destination = ObjectGenerator.create_active_account()
        payload = PayloadGenerator.create_tef_payload(source["account_id"], destination["account_id"], 1_000)

        status, response = RequestGenerator.POST_transfer(payload, new_key())

        assert status == 422
        assert response["code"] == "QIT001017"
        assert ObjectGenerator.balance_of(source["account_id"]) == 1_000

    def test_same_account_is_422(self):
        source = ObjectGenerator.create_active_account(initial_balance=1_000)
        payload = PayloadGenerator.create_tef_payload(source["account_id"], source["account_id"], 100)

        status, response = RequestGenerator.POST_transfer(payload, new_key())

        assert status == 422
        assert response["code"] == "QIT001018"

    def test_both_accounts_must_be_active(self):
        active = ObjectGenerator.create_active_account(initial_balance=5_000)
        blocked = ObjectGenerator.create_active_account(initial_balance=5_000)
        RequestGenerator.PATCH_account_status(blocked["account_id"], "BLOCKED")

        to_blocked = PayloadGenerator.create_tef_payload(active["account_id"], blocked["account_id"], 100)
        from_blocked = PayloadGenerator.create_tef_payload(blocked["account_id"], active["account_id"], 100)

        for payload in (to_blocked, from_blocked):
            status, response = RequestGenerator.POST_transfer(payload, new_key())
            assert status == 409
            assert response["code"] == "QIT001013"

    def test_unknown_accounts_are_404(self):
        existing = ObjectGenerator.create_active_account(initial_balance=5_000)

        for source_id, destination_id in (
            (str(uuid4()), existing["account_id"]),
            (existing["account_id"], str(uuid4())),
            ("nao-e-uuid", existing["account_id"]),
        ):
            payload = PayloadGenerator.create_tef_payload(source_id, destination_id, 100)
            status, response = RequestGenerator.POST_transfer(payload, new_key())
            assert status == 404, (source_id, destination_id)
            assert response["code"] == "QIT001009"

    def test_pix_and_ted_are_not_open_yet(self):
        """Sprint 2a só abre TEF. PIX e TED chegam no mesmo endereço, no sprint 2b."""
        source = ObjectGenerator.create_active_account(initial_balance=5_000)
        destination = ObjectGenerator.create_active_account()
        payload = PayloadGenerator.create_tef_payload(source["account_id"], destination["account_id"], 100)
        payload["method"] = "PIX"

        status, response = RequestGenerator.POST_transfer(payload, new_key())

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_get_and_list_transfers(self):
        source = ObjectGenerator.create_active_account(initial_balance=10_000)
        destination = ObjectGenerator.create_active_account()

        ids = []
        for amount in (100, 200, 300):
            payload = PayloadGenerator.create_tef_payload(source["account_id"], destination["account_id"], amount)
            _, transfer = RequestGenerator.POST_transfer(payload, new_key())
            ids.append(transfer["transfer_id"])

        status, transfer = RequestGenerator.GET_transfer(ids[0])
        assert status == 200
        assert transfer["amount"] == 100

        status, page = RequestGenerator.GET_account_transfers(destination["account_id"], {"limit": "2"})
        assert status == 200
        assert [item["transfer_id"] for item in page["items"]] == [ids[2], ids[1]]

        status, page = RequestGenerator.GET_account_transfers(
            destination["account_id"], {"limit": "2", "cursor": page["next_cursor"]}
        )
        assert [item["transfer_id"] for item in page["items"]] == [ids[0]]
        assert page["next_cursor"] is None

    def test_night_limit(self):
        """Das 20h às 6h (Brasília) a soma das saídas tem teto de R$ 1.000,00.

        O teste roda a qualquer hora e confere o lado certo da regra: à
        noite, o centavo acima do teto é recusado; de dia, passa. Depende
        do relógio da sua máquina e do banco concordarem — é o caso
        quando os dois rodam no mesmo computador.
        """
        try:
            from zoneinfo import ZoneInfo

            local_hour = datetime.now(ZoneInfo("America/Sao_Paulo")).hour
        except Exception:
            pytest.skip("sem base de fusos nesta máquina (Windows sem o pacote tzdata)")

        is_night = local_hour >= 20 or local_hour < 6

        source = ObjectGenerator.create_active_account(initial_balance=300_000)
        destination = ObjectGenerator.create_active_account()

        at_limit = PayloadGenerator.create_tef_payload(source["account_id"], destination["account_id"], NIGHT_LIMIT)
        status, _ = RequestGenerator.POST_transfer(at_limit, new_key())
        assert status == 201, "exatamente no teto é permitido"

        one_more_cent = PayloadGenerator.create_tef_payload(source["account_id"], destination["account_id"], 1)
        status, response = RequestGenerator.POST_transfer(one_more_cent, new_key())

        if is_night:
            assert status == 422
            assert response["code"] == "QIT001019"
        else:
            assert status == 201
