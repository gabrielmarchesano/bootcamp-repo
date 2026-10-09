"""Garantias que o banco sustenta, provadas pela porta da frente.

Estas regras moram no `database.sql` (FK composta, UNIQUE, CHECK, trigger
de append-only) e, antes, eram testadas inserindo linhas direto nas
tabelas. Aqui elas são conferidas como o cliente as vê: pelo que a API
aceita, recusa e devolve. Se um caminho novo esquecer a regra no
controller, o banco recusa e o teste acusa — com um 500 no lugar do
código de erro esperado.
"""

import re
from uuid import uuid4

from tests.conftest import ERROR_FIELDS
from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator

EXTERNAL_KEY = "fornecedor@externo.com"  # chave do mock do DICT (src/utils/dict_mock.py)


def key() -> str:
    return str(uuid4())


def rid(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


class TestPixGuarantees:
    def test_e2e_from_inquiry_is_single_use_and_bound_to_the_account(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        other = ObjectGenerator.create_active_account(initial_balance=20_000)
        inquiry = ObjectGenerator.lookup(EXTERNAL_KEY, payer["account_id"])
        payload = PayloadGenerator.create_pix_key_payload(EXTERNAL_KEY, inquiry["end_to_end_id"], 5_000)

        status, _ = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, key())
        assert status == 202

        # uma vez só: outra transferência com o mesmo e2e
        status, error = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, key())
        assert status == 409
        assert error["code"] == "QIT001022"
        assert set(error) == ERROR_FIELDS

        # e só para a conta que consultou
        other_inquiry = ObjectGenerator.lookup(EXTERNAL_KEY, other["account_id"])
        stolen = PayloadGenerator.create_pix_key_payload(EXTERNAL_KEY, other_inquiry["end_to_end_id"], 5_000)
        status, error = RequestGenerator.POST_pix_transfer(payer["account_id"], stolen, key())
        assert status == 404
        assert error["code"] == "QIT001036"

        assert ObjectGenerator.balance_of(payer["account_id"]) == 15_000
        assert ObjectGenerator.balance_of(other["account_id"]) == 20_000

    def test_pix_key_needs_inquiry_and_e2e_has_bcb_format(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)

        inquiry = ObjectGenerator.lookup(EXTERNAL_KEY, payer["account_id"])
        # E + ISPB (8) + yyyyMMddHHmm (12) + 11 caracteres
        assert re.fullmatch(r"E\d{8}\d{12}[A-Za-z0-9]{11}", inquiry["end_to_end_id"]), inquiry["end_to_end_id"]

        invented = "E13370001" + "202610091230" + "ABCDEFGHIJK"
        payload = PayloadGenerator.create_pix_key_payload(EXTERNAL_KEY, invented, 1_000)
        status, error = RequestGenerator.POST_pix_transfer(payer["account_id"], payload, key())

        assert status == 404
        assert error["code"] == "QIT001036"
        assert ObjectGenerator.balance_of(payer["account_id"]) == 20_000

    def test_reversal_needs_original_and_reason(self):
        customer = ObjectGenerator.create_active_account()
        status, incoming = RequestGenerator.POST_webhook_spi(
            PayloadGenerator.create_spi_received_payload(customer["account_number"], 10_000)
        )
        assert status == 200

        status, _ = RequestGenerator.POST_pix_reversal(
            customer["account_id"], incoming["incoming_transfer_id"], {"amount": 1_000}, key()
        )
        assert status == 400, "sem motivo, o schema recusa"

        status, error = RequestGenerator.POST_pix_reversal(
            customer["account_id"], str(uuid4()), {"amount": 1_000, "reversal_reason": "CLIENT_REQUEST"}, key()
        )
        assert status == 404, "sem entrada original, não há devolução"
        assert error["code"] == "QIT001038"

        status, reversal = RequestGenerator.POST_pix_reversal(
            customer["account_id"], incoming["incoming_transfer_id"], {"amount": 1_000, "reversal_reason": "CLIENT_REQUEST"}, key()
        )
        assert status == 202, reversal
        assert reversal["pix"]["pix_transfer_type"] == "REVERSAL"
        assert reversal["pix"]["end_to_end_id"].startswith("D")
        assert ObjectGenerator.balance_of(customer["account_id"]) == 9_000


class TestCardGuarantees:
    def test_credit_card_wallet_must_belong_to_the_same_account(self):
        owner = ObjectGenerator.create_active_account()
        wallet = ObjectGenerator.create_credit_wallet(owner["account_id"])
        neighbour = ObjectGenerator.create_active_account()

        # a carteira de outra conta não serve
        status, error = RequestGenerator.POST_card(neighbour["account_id"], PayloadGenerator.create_card_payload(functions="CREDIT"))
        assert status == 422
        assert error["code"] == "QIT001045"
        assert set(error) == ERROR_FIELDS

        card = ObjectGenerator.create_card(owner["account_id"], functions="CREDIT")
        assert card["account_id"] == owner["account_id"]
        assert card["wallet_id"] == wallet["wallet_id"]

    def test_one_live_wallet_per_account_and_fine_cap(self):
        customer = ObjectGenerator.create_active_account()
        wallet = ObjectGenerator.create_credit_wallet(customer["account_id"])

        status, error = RequestGenerator.POST_credit_wallet(customer["account_id"], PayloadGenerator.create_credit_wallet_payload())
        assert status == 409
        assert error["code"] == "QIT001030"

        too_high = PayloadGenerator.create_credit_wallet_payload()
        too_high["fine_rate"] = 0.05
        status, _ = RequestGenerator.POST_credit_wallet(ObjectGenerator.create_active_account()["account_id"], too_high)
        assert status == 400, "multa acima de 2% não passa"

        # "viva" é o que importa: fechada a primeira, a conta abre outra
        assert RequestGenerator.PATCH_credit_wallet_status(wallet["wallet_id"], "CLOSED")[0] == 200
        status, again = RequestGenerator.POST_credit_wallet(customer["account_id"], PayloadGenerator.create_credit_wallet_payload())
        assert status == 201
        assert again["wallet_id"] != wallet["wallet_id"]

    def test_declined_needs_reason_and_refund_cannot_pass_capture(self):
        customer = ObjectGenerator.create_active_account(initial_balance=10_000)
        card = ObjectGenerator.create_card(customer["account_id"], functions="DEBIT")

        _, declined = RequestGenerator.POST_card_authorization(
            PayloadGenerator.create_authorization_payload(card["card_id"], 50_000, function="DEBIT")
        )
        assert declined["status"] == "DECLINED"
        assert declined["denial_reason"] == "INSUFFICIENT_FUNDS"

        payload = PayloadGenerator.create_authorization_payload(card["card_id"], 4_000, function="DEBIT")
        RequestGenerator.POST_card_authorization(payload)
        capture = {"capture_id": rid("cap"), "authorization_id": payload["authorization_id"], "amount": 4_000}
        RequestGenerator.POST_card_capture(capture)
        RequestGenerator.POST_card_capture(capture)  # mesma captura de novo: um evento só

        status, error = RequestGenerator.POST_card_refund(
            {"refund_id": rid("ref"), "authorization_id": payload["authorization_id"], "amount": 4_001}
        )
        assert status == 422
        assert error["code"] == "QIT001035"

        _, authorization = RequestGenerator.GET_card_authorization(payload["authorization_id"])
        assert authorization["refunded_amount"] == 0
        assert [event["type"] for event in authorization["events"]] == ["AUTHORIZATION", "CAPTURE"]


class TestHistoryGuarantees:
    def test_new_histories_and_lists_are_append_only(self):
        """Cada troca de status acrescenta um evento; os anteriores nunca mudam."""
        customer = ObjectGenerator.create_active_account()
        card = ObjectGenerator.create_card(customer["account_id"], functions="DEBIT")
        seen = card["status_events"]

        for status in ("BLOCKED", "ACTIVE", "CANCELED"):
            code, after = RequestGenerator.PATCH_card_status(card["card_id"], status)
            assert code == 200, after
            assert len(after["status_events"]) == len(seen) + 1
            assert after["status_events"][: len(seen)] == seen, "o histórico só cresce"
            assert after["status_events"][-1]["to_status"] == status
            seen = after["status_events"]

        code, error = RequestGenerator.PATCH_card_status(card["card_id"], "ACTIVE")
        assert code == 409, "CANCELED é final"
        assert error["code"] == "QIT001032"
        _, final = RequestGenerator.GET_card(card["card_id"])
        assert final["status_events"] == seen
