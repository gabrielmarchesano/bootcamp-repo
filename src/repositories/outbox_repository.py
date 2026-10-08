from typing import List

from sqlalchemy import func

from database import Context
from models import OutboxEvent, OutboxEventStatus
from repositories.enumerator_repository import EnumeratorRepository


class OutboxRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

    def add(self, event_type: str, aggregate_type: str, aggregate, payload: dict) -> None:
        """Grava o evento para a IF. `aggregate` é a entidade: o evento leva a `key` pública dela.

        A `key` só existe depois do flush (default do lado do Python); se a
        entidade ainda não foi gravada, o flush acontece aqui.
        """
        if aggregate.key is None:
            self.session.flush()

        event = OutboxEvent()
        event.type = event_type
        event.aggregate_type = aggregate_type
        event.aggregate_id = aggregate.key
        event.payload = payload
        # O banco não tem DEFAULT: todo evento nasce PENDING, dito aqui.
        event.status = self.enumerators.get(OutboxEventStatus, OutboxEventStatus.PENDING)

        self.session.add(event)

    # ── despacho (job dispatch_outbox_events) ───────────────────────

    def list_pending(self, limit: int) -> List[OutboxEvent]:
        """Os PENDING mais antigos, SEM lock: a chamada à IF acontece fora da transação."""
        return (
            self.session.query(OutboxEvent)
            .join(OutboxEvent.status)
            .filter(OutboxEventStatus.enumerator == OutboxEventStatus.PENDING)
            .order_by(OutboxEvent.id)
            .limit(limit)
            .all()
        )

    def lock_pending(self, event_id: int):
        """Trava o evento se ainda estiver PENDING; SKIP LOCKED: outro despachante já o tem."""
        return (
            self.session.query(OutboxEvent)
            .join(OutboxEvent.status)
            .filter(OutboxEvent.id == event_id, OutboxEventStatus.enumerator == OutboxEventStatus.PENDING)
            .populate_existing()
            .with_for_update(skip_locked=True, of=OutboxEvent)
            .first()
        )

    def mark_sent(self, event: OutboxEvent) -> None:
        event.status = self.enumerators.get(OutboxEventStatus, OutboxEventStatus.SENT)
        event.attempts = event.attempts + 1
        event.sent_at = func.now()

    def mark_failed_attempt(self, event: OutboxEvent, max_attempts: int) -> None:
        event.attempts = event.attempts + 1
        if event.attempts >= max_attempts:
            event.status = self.enumerators.get(OutboxEventStatus, OutboxEventStatus.FAILED)
