from datetime import datetime, time, timedelta
from uuid import uuid4

import pytest

from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator
from tests.utils.object_generator import is_business_day, next_business_day_after

# Tarifa de TED do seed (database/database.sql).
TED_FEE = 1_000


def key() -> str:
    return str(uuid4())


def local_now() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/Sao_Paulo"))


def ted_window_open() -> bool:
    """Mesma regra da API: dia útil (incl. feriados do seed), das 6h30 às 17h."""
    now = local_now()
    return is_business_day(now.date()) and time(6, 30) <= now.time() < time(17, 0)


def next_business_day() -> str:
    """Próximo dia útil (pula fim de semana E feriados), como a API faz."""
    return next_business_day_after(local_now().date()).isoformat()


needs_window = pytest.mark.skipif(not ted_window_open(), reason="TED imediata só roda na janela do STR (dia útil, 6h30–17h)")


class TestTed:
    @needs_window
    def test_ted_now_debits_amount_and_fee_and_settles_by_webhook(self):
        source = ObjectGenerator.create_active_account(initial_balance=50_000)

        status, transfer = RequestGenerator.POST_ted_transfer(
            source["account_id"], PayloadGenerator.create_ted_payload(20_000), key()
        )
        assert status == 202, transfer
        assert transfer["status"] == "SENT"
        assert transfer["fee"] == TED_FEE
        assert ObjectGenerator.balance_of(source["account_id"]) == 50_000 - 20_000 - TED_FEE

        status, settled = RequestGenerator.POST_webhook_str(
            PayloadGenerator.create_str_payload("SETTLED", str_control_number=transfer["ted"]["str_control_number"])
        )
        assert status == 200
        assert settled["status"] == "COMPLETED"

    @needs_window
    def test_returned_ted_gives_back_the_amount_but_not_the_fee(self):
        source = ObjectGenerator.create_active_account(initial_balance=50_000)
        _, transfer = RequestGenerator.POST_ted_transfer(source["account_id"], PayloadGenerator.create_ted_payload(20_000), key())

        status, returned = RequestGenerator.POST_webhook_str(
            PayloadGenerator.create_str_payload(
                "RETURNED", str_control_number=transfer["ted"]["str_control_number"], reason="conta encerrada no destino"
            )
        )

        assert status == 200
        assert returned["status"] == "RETURNED"
        assert ObjectGenerator.balance_of(source["account_id"]) == 50_000 - TED_FEE

    def test_outside_window_without_date_is_422_inside_is_202(self):
        source = ObjectGenerator.create_active_account(initial_balance=50_000)

        status, body = RequestGenerator.POST_ted_transfer(source["account_id"], PayloadGenerator.create_ted_payload(1_000), key())

        if ted_window_open():
            assert status == 202, body
        else:
            assert status == 422
            assert body["code"] == "QIT001025"

    def test_scheduled_ted_does_not_debit_and_can_be_canceled(self):
        source = ObjectGenerator.create_active_account(initial_balance=5_000)

        status, transfer = RequestGenerator.POST_ted_transfer(
            source["account_id"], PayloadGenerator.create_ted_payload(30_000, next_business_day()), key()
        )
        assert status == 202, transfer
        assert transfer["status"] == "SCHEDULED"
        assert ObjectGenerator.balance_of(source["account_id"]) == 5_000

        status, canceled = RequestGenerator.PATCH_transfer_cancel(transfer["transfer_id"])
        assert status == 200
        assert canceled["status"] == "CANCELED"

        status, error = RequestGenerator.PATCH_transfer_cancel(transfer["transfer_id"])
        assert status == 409
        assert error["code"] == "QIT001028"

    def test_schedule_date_must_be_a_future_business_day(self):
        source = ObjectGenerator.create_active_account(initial_balance=5_000)
        today = local_now().date().isoformat()
        saturday = local_now().date() + timedelta(days=(5 - local_now().weekday()) % 7 or 7)

        for bad in (today, saturday.isoformat(), "2026-02-30"):
            status, error = RequestGenerator.POST_ted_transfer(
                source["account_id"], PayloadGenerator.create_ted_payload(1_000, bad), key()
            )
            assert status == 422, bad
            assert error["code"] == "QIT001049"

    def test_ted_to_this_institution_is_refused(self):
        source = ObjectGenerator.create_active_account(initial_balance=5_000)
        payload = PayloadGenerator.create_ted_payload(1_000, next_business_day())
        payload["target_account"]["ispb"] = "13370001"

        status, error = RequestGenerator.POST_ted_transfer(source["account_id"], payload, key())

        assert status == 422
        assert error["code"] == "QIT001042"

    def test_ted_received_credits_the_account(self):
        customer = ObjectGenerator.create_active_account()
        payload = PayloadGenerator.create_spi_received_payload(customer["account_number"], 12_345)
        payload["event"] = "RECEIVED"
        payload["external_id"] = f"STR{uuid4().hex[:20]}"

        status, incoming = RequestGenerator.POST_webhook_str(payload)

        assert status == 200
        assert incoming["rail"] == "STR"
        assert incoming["status"] == "CREDITED"
        assert ObjectGenerator.balance_of(customer["account_id"]) == 12_345

    def test_unknown_control_number_is_200_ignored(self):
        status, body = RequestGenerator.POST_webhook_str(
            PayloadGenerator.create_str_payload("SETTLED", str_control_number="naoexiste")
        )

        assert status == 200
        assert body["result"] == "IGNORED"


def test_cancel_of_tef_is_409():
    source = ObjectGenerator.create_active_account(initial_balance=5_000)
    destination = ObjectGenerator.create_active_account()
    _, tef = RequestGenerator.POST_transfer(
        PayloadGenerator.create_tef_payload(source["account_id"], destination["account_id"], 100), key()
    )

    status, error = RequestGenerator.PATCH_transfer_cancel(tef["transfer_id"])

    assert status == 409
    assert error["code"] == "QIT001028"