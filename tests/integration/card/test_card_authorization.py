from uuid import uuid4

from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


def rid(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def setup_credit(total_limit: int = 100_000):
    customer = ObjectGenerator.create_active_account()
    wallet = ObjectGenerator.create_credit_wallet(customer["account_id"], total_limit=total_limit)
    card = ObjectGenerator.create_card(customer["account_id"])
    return customer, wallet, card


def used_limit(wallet_id: str) -> int:
    _, wallet = RequestGenerator.GET_credit_wallet(wallet_id)
    return wallet["used_limit"]


def held_balance(account_id: str) -> int:
    _, account = RequestGenerator.GET_account(account_id)
    return account["held_balance"]


class TestAuthorizationDecision:
    def test_approved_credit_reserves_limit(self):
        _, wallet, card = setup_credit()

        status, decision = RequestGenerator.POST_card_authorization(
            PayloadGenerator.create_authorization_payload(card["card_id"], 25_000)
        )

        assert status == 200
        assert decision["status"] == "APPROVED"
        assert decision["response_code"] == "00"
        assert len(decision["approval_code"]) == 6
        assert used_limit(wallet["wallet_id"]) == 25_000

    def test_decline_is_200_with_reason(self):
        """A rede espera a decisão no corpo. 4xx seria lido como emissor fora do ar."""
        _, wallet, card = setup_credit(total_limit=1_000)

        status, decision = RequestGenerator.POST_card_authorization(
            PayloadGenerator.create_authorization_payload(card["card_id"], 1_001)
        )

        assert status == 200
        assert decision["status"] == "DECLINED"
        assert decision["response_code"] == "51"
        assert decision["denial_reason"] == "INSUFFICIENT_LIMIT"
        assert used_limit(wallet["wallet_id"]) == 0

    def test_replay_returns_the_same_decision(self):
        _, wallet, card = setup_credit()
        payload = PayloadGenerator.create_authorization_payload(card["card_id"], 5_000)

        _, first = RequestGenerator.POST_card_authorization(payload)
        _, second = RequestGenerator.POST_card_authorization(payload)

        assert first == second
        assert used_limit(wallet["wallet_id"]) == 5_000

    def test_unknown_card_is_200_code_14(self):
        status, decision = RequestGenerator.POST_card_authorization(
            PayloadGenerator.create_authorization_payload(str(uuid4()), 100)
        )

        assert status == 200
        assert decision["response_code"] == "14"

    def test_debit_holds_balance(self):
        customer = ObjectGenerator.create_active_account(initial_balance=10_000)
        card = ObjectGenerator.create_card(customer["account_id"], functions="DEBIT")

        _, approved = RequestGenerator.POST_card_authorization(
            PayloadGenerator.create_authorization_payload(card["card_id"], 6_000, function="DEBIT")
        )
        _, declined = RequestGenerator.POST_card_authorization(
            PayloadGenerator.create_authorization_payload(card["card_id"], 6_000, function="DEBIT")
        )

        assert approved["status"] == "APPROVED"
        assert declined["denial_reason"] == "INSUFFICIENT_FUNDS"
        assert held_balance(customer["account_id"]) == 6_000
        assert ObjectGenerator.balance_of(customer["account_id"]) == 10_000

    def test_debit_card_cannot_buy_on_credit(self):
        customer = ObjectGenerator.create_active_account(initial_balance=10_000)
        card = ObjectGenerator.create_card(customer["account_id"], functions="DEBIT")

        _, decision = RequestGenerator.POST_card_authorization(
            PayloadGenerator.create_authorization_payload(card["card_id"], 100, function="CREDIT")
        )

        assert decision["denial_reason"] == "FUNCTION_NOT_SUPPORTED"

    def test_blocked_card_and_blocked_wallet_decline(self):
        _, wallet, card = setup_credit()

        RequestGenerator.PATCH_card_status(card["card_id"], "BLOCKED")
        _, by_card = RequestGenerator.POST_card_authorization(PayloadGenerator.create_authorization_payload(card["card_id"], 100))
        assert by_card["denial_reason"] == "CARD_NOT_ACTIVE"

        RequestGenerator.PATCH_card_status(card["card_id"], "ACTIVE")
        RequestGenerator.PATCH_credit_wallet_status(wallet["wallet_id"], "BLOCKED")
        _, by_wallet = RequestGenerator.POST_card_authorization(PayloadGenerator.create_authorization_payload(card["card_id"], 100))
        assert by_wallet["denial_reason"] == "WALLET_NOT_ACTIVE"

    def test_installments_only_on_credit(self):
        customer = ObjectGenerator.create_active_account(initial_balance=10_000)
        card = ObjectGenerator.create_card(customer["account_id"], functions="DEBIT")

        status, error = RequestGenerator.POST_card_authorization(
            PayloadGenerator.create_authorization_payload(card["card_id"], 1_000, function="DEBIT", installment_count=3)
        )

        assert status == 400


class TestAuthorizationEvents:
    def test_incremental_and_partial_reversal(self):
        _, wallet, card = setup_credit()
        payload = PayloadGenerator.create_authorization_payload(card["card_id"], 10_000)
        RequestGenerator.POST_card_authorization(payload)
        auth_id = payload["authorization_id"]

        increment_id = rid("inc")
        status, incremented = RequestGenerator.POST_card_increment(auth_id, {"request_id": increment_id, "amount": 5_000})
        assert status == 200 and incremented["decision"] == "APPROVED"
        assert incremented["authorized_amount"] == 15_000

        _, replay = RequestGenerator.POST_card_increment(auth_id, {"request_id": increment_id, "amount": 5_000})
        assert replay["authorized_amount"] == 15_000

        status, partial = RequestGenerator.POST_card_reversal(auth_id, {"request_id": rid("rev"), "amount": 4_000})
        assert status == 200
        assert partial["status"] == "APPROVED"
        assert partial["authorized_amount"] == 11_000
        assert used_limit(wallet["wallet_id"]) == 11_000
        assert [e["type"] for e in partial["events"]] == ["AUTHORIZATION", "INCREMENTAL_AUTHORIZATION", "PARTIAL_REVERSAL"]

    def test_full_reversal_releases_everything(self):
        customer = ObjectGenerator.create_active_account(initial_balance=10_000)
        card = ObjectGenerator.create_card(customer["account_id"], functions="DEBIT")
        payload = PayloadGenerator.create_authorization_payload(card["card_id"], 3_000, function="DEBIT")
        RequestGenerator.POST_card_authorization(payload)

        status, reversed_ = RequestGenerator.POST_card_reversal(payload["authorization_id"], {"request_id": rid("rev")})

        assert status == 200
        assert reversed_["status"] == "REVERSED"
        assert held_balance(customer["account_id"]) == 0

        status, error = RequestGenerator.POST_card_capture(
            {"capture_id": rid("cap"), "authorization_id": payload["authorization_id"], "amount": 3_000}
        )
        assert status == 409
        assert error["code"] == "QIT001047"

    def test_debit_capture_swaps_hold_for_ledger_entry(self):
        customer = ObjectGenerator.create_active_account(initial_balance=10_000)
        card = ObjectGenerator.create_card(customer["account_id"], functions="DEBIT")
        payload = PayloadGenerator.create_authorization_payload(card["card_id"], 3_000, function="DEBIT")
        RequestGenerator.POST_card_authorization(payload)
        capture = {"capture_id": rid("cap"), "authorization_id": payload["authorization_id"], "amount": 3_200}

        status, captured = RequestGenerator.POST_card_capture(capture)
        assert status == 200
        assert captured["status"] == "CAPTURED"
        assert captured["captured_amount"] == 3_200
        assert held_balance(customer["account_id"]) == 0
        assert ObjectGenerator.balance_of(customer["account_id"]) == 6_800

        _, again = RequestGenerator.POST_card_capture(capture)
        assert again["captured_amount"] == 3_200
        assert ObjectGenerator.balance_of(customer["account_id"]) == 6_800

        _, statement = RequestGenerator.GET_statement(customer["account_id"])
        assert statement["items"][0]["type"] == "DEBIT_PURCHASE"

    def test_refund_is_an_event_and_status_stays_captured(self):
        customer = ObjectGenerator.create_active_account(initial_balance=10_000)
        card = ObjectGenerator.create_card(customer["account_id"], functions="DEBIT")
        payload = PayloadGenerator.create_authorization_payload(card["card_id"], 5_000, function="DEBIT")
        RequestGenerator.POST_card_authorization(payload)
        auth_id = payload["authorization_id"]
        RequestGenerator.POST_card_capture({"capture_id": rid("cap"), "authorization_id": auth_id, "amount": 5_000})

        status, partial = RequestGenerator.POST_card_refund({"refund_id": rid("ref"), "authorization_id": auth_id, "amount": 2_000})
        assert status == 200
        assert partial["status"] == "CAPTURED"
        assert partial["refunded_amount"] == 2_000
        assert partial["events"][-1]["type"] == "PARTIAL_REFUND"

        status, error = RequestGenerator.POST_card_refund({"refund_id": rid("ref"), "authorization_id": auth_id, "amount": 3_001})
        assert status == 422
        assert error["code"] == "QIT001035"

        _, full = RequestGenerator.POST_card_refund({"refund_id": rid("ref"), "authorization_id": auth_id, "amount": 3_000})
        assert full["events"][-1]["type"] == "REFUND"
        assert ObjectGenerator.balance_of(customer["account_id"]) == 10_000

    def test_unknown_authorization_is_404(self):
        status, error = RequestGenerator.POST_card_capture({"capture_id": rid("cap"), "authorization_id": "nada", "amount": 1})

        assert status == 404
        assert error["code"] == "QIT001046"


class TestInvoices:
    def test_installments_spread_over_current_and_future_invoices(self):
        _, wallet, card = setup_credit()
        payload = PayloadGenerator.create_authorization_payload(card["card_id"], 10_000, installment_count=3)
        RequestGenerator.POST_card_authorization(payload)
        RequestGenerator.POST_card_capture(
            {"capture_id": rid("cap"), "authorization_id": payload["authorization_id"], "amount": 10_000}
        )

        status, invoices = RequestGenerator.GET_wallet_invoices(wallet["wallet_id"])
        assert status == 200
        items = sorted(invoices["items"], key=lambda invoice: invoice["reference_month"])
        assert [invoice["status"] for invoice in items] == ["OPEN", "FUTURE", "FUTURE"]
        assert [invoice["total_amount"] for invoice in items] == [3_334, 3_333, 3_333]
        assert used_limit(wallet["wallet_id"]) == 10_000

        status, detail = RequestGenerator.GET_invoice(items[1]["invoice_id"])
        assert status == 200
        assert detail["items"][0]["installment_number"] == 2
        assert detail["items"][0]["installment_total"] == 3

        _, only_open = RequestGenerator.GET_wallet_invoices(wallet["wallet_id"], {"status": "OPEN"})
        assert len(only_open["items"]) == 1

    def test_credit_refund_frees_limit_and_lands_negative_on_invoice(self):
        _, wallet, card = setup_credit()
        payload = PayloadGenerator.create_authorization_payload(card["card_id"], 8_000)
        RequestGenerator.POST_card_authorization(payload)
        RequestGenerator.POST_card_capture({"capture_id": rid("cap"), "authorization_id": payload["authorization_id"], "amount": 8_000})

        RequestGenerator.POST_card_refund({"refund_id": rid("ref"), "authorization_id": payload["authorization_id"], "amount": 8_000})

        assert used_limit(wallet["wallet_id"]) == 0
        _, invoices = RequestGenerator.GET_wallet_invoices(wallet["wallet_id"], {"status": "OPEN"})
        assert invoices["items"][0]["total_amount"] == 0