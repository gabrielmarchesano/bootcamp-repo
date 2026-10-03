from uuid import uuid4

from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


class TestAccountStatusHistory:
    """A coluna `status` diz ONDE a conta está; `status_events` diz desde quando e por onde passou."""

    def test_birth_is_the_first_event(self):
        """Toda conta nasce com um evento: null → status inicial (o "nulo ao nascer")."""
        customer = ObjectGenerator.create_active_account()

        status, account = RequestGenerator.GET_account(customer["account_id"])

        assert status == 200
        events = account["status_events"]
        assert len(events) == 1
        assert events[0]["from_status"] is None
        assert events[0]["to_status"] == "ACTIVE"

    def test_every_transition_leaves_one_event_chained_to_the_previous(self):
        """PENDING → ACTIVE → BLOCKED → ACTIVE → CLOSED: cinco eventos, cada um começando onde o anterior terminou."""
        payload = PayloadGenerator.create_customer_payload(is_pep=True)
        _, customer = RequestGenerator.POST_customer(payload)
        account_id = customer["account_id"]

        for new_status, reason in (
            ("ACTIVE", "PEP aprovado pelo compliance"),
            ("BLOCKED", "suspeita de fraude"),
            ("ACTIVE", "fraude descartada"),
            ("CLOSED", "pedido do cliente"),
        ):
            status, _ = RequestGenerator.PATCH_account_status(account_id, new_status, reason)
            assert status == 200

        _, account = RequestGenerator.GET_account(account_id)
        events = account["status_events"]

        assert [(e["from_status"], e["to_status"]) for e in events] == [
            (None, "PENDING"),
            ("PENDING", "ACTIVE"),
            ("ACTIVE", "BLOCKED"),
            ("BLOCKED", "ACTIVE"),
            ("ACTIVE", "CLOSED"),
        ]
        assert events[0]["reason"] == "PEP_REVIEW"
        assert events[2]["reason"] == "suspeita de fraude"
        assert events[-1]["to_status"] == account["status"]

    def test_refused_transition_leaves_no_event(self):
        """Transição recusada (409) não deixa rastro: o histórico conta o que aconteceu, não o que foi tentado."""
        customer = ObjectGenerator.create_active_account()

        status, _ = RequestGenerator.PATCH_account_status(customer["account_id"], "REJECTED")
        assert status == 409

        _, account = RequestGenerator.GET_account(customer["account_id"])
        assert len(account["status_events"]) == 1

    def test_final_status_is_final(self):
        """Estado final é final, e é ele que responde 409: conta encerrada não volta nem recebe TEF."""
        source = ObjectGenerator.create_active_account(initial_balance=5_000)
        closed = ObjectGenerator.create_active_account()

        status, _ = RequestGenerator.PATCH_account_status(closed["account_id"], "CLOSED", "pedido do cliente")
        assert status == 200

        for new_status in ("ACTIVE", "BLOCKED"):
            status, response = RequestGenerator.PATCH_account_status(closed["account_id"], new_status)
            assert status == 409
            assert response["code"] == "QIT001012"

        payload = PayloadGenerator.create_tef_payload(source["account_id"], closed["account_id"], 100)
        status, response = RequestGenerator.POST_transfer(payload, str(uuid4()))
        assert status == 409
        assert response["code"] == "QIT001013"