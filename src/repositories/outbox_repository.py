from uuid import UUID

from database import Context
from models import OutboxEvent, OutboxEventStatus
from repositories.enumerator_repository import EnumeratorRepository


class OutboxRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

    def add(self, event_type: str, aggregate_type: str, aggregate_id: UUID, payload: dict) -> None:
        event = OutboxEvent()
        event.type = event_type
        event.aggregate_type = aggregate_type
        event.aggregate_id = aggregate_id
        event.payload = payload
        # O banco não tem mais DEFAULT: todo evento nasce PENDING, dito aqui.
        event.status = self.enumerators.get(OutboxEventStatus, OutboxEventStatus.PENDING)

        self.session.add(event)