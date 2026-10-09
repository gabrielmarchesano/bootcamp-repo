from typing import List, Optional
from uuid import UUID

from sqlalchemy import func

from database import Context
from models import Card, CardStatus, CardStatusEvent
from repositories.enumerator_repository import EnumeratorRepository
from repositories.status_event_recorder import record_status_event


class CardRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

    def create(self, fields: dict, status: str) -> Card:
        card = Card()
        for name, value in fields.items():
            setattr(card, name, value)
        card.status = self.enumerators.get(CardStatus, status)

        self.session.add(card)
        record_status_event(self.session, CardStatusEvent, "card", card, None, card.status, None)
        self.session.flush()
        return card

    def get_by_key(self, card_key: UUID) -> Optional[Card]:
        return self.session.query(Card).filter(Card.key == card_key).first()

    def list_by_account(self, account_id: UUID) -> List[Card]:
        return self.session.query(Card).filter(Card.account_id == account_id).order_by(Card.created_at).all()

    def lock(self, card_id: UUID) -> Optional[Card]:
        return (
            self.session.query(Card).filter(Card.id == card_id).populate_existing().with_for_update().first()
        )

    def update_status(self, card: Card, new_status: str, reason: Optional[str]) -> None:
        old_status = card.status
        card.status = self.enumerators.get(CardStatus, new_status)
        card.updated_at = func.now()
        record_status_event(self.session, CardStatusEvent, "card", card, old_status, card.status, reason)
