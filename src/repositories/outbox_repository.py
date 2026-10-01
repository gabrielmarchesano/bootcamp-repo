from uuid import UUID

from database import Context
from models import OutboxEvent


class OutboxRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def add(self, event_type: str, aggregate_type: str, aggregate_id: UUID, payload: dict) -> None:
        event = OutboxEvent()
        event.type = event_type
        event.aggregate_type = aggregate_type
        event.aggregate_id = aggregate_id
        event.payload = payload

        self.session.add(event)
