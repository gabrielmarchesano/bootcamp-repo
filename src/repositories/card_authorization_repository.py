from typing import List, Optional

from sqlalchemy import func

from database import Context
from models import CardAuthorization, CardAuthorizationEvent, CardAuthorizationStatus, CardAuthorizationStatusEvent
from repositories.enumerator_repository import EnumeratorRepository
from repositories.status_event_recorder import record_status_event


class CardAuthorizationRepository:
    """A autorização e os seus dois históricos.

    • card_authorization_status_event: por onde o STATUS passou.
    • card_authorization_event: o que aconteceu com o DINHEIRO.
    Os dois são gravados aqui, sempre junto da mudança que contam.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

    def get_by_authorization_id(self, authorization_id: str) -> Optional[CardAuthorization]:
        return (
            self.session.query(CardAuthorization)
            .filter(CardAuthorization.authorization_id == authorization_id)
            .first()
        )

    def lock_by_authorization_id(self, authorization_id: str) -> Optional[CardAuthorization]:
        return (
            self.session.query(CardAuthorization)
            .filter(CardAuthorization.authorization_id == authorization_id)
            .populate_existing()
            .with_for_update()
            .first()
        )

    def create(self, fields: dict, status: str) -> CardAuthorization:
        authorization = CardAuthorization()
        for name, value in fields.items():
            setattr(authorization, name, value)
        authorization.captured_amount = 0
        authorization.refunded_amount = 0
        authorization.status = self.enumerators.get(CardAuthorizationStatus, status)

        self.session.add(authorization)
        record_status_event(
            self.session, CardAuthorizationStatusEvent, "card_authorization", authorization, None, authorization.status, None
        )
        self.session.flush()
        return authorization

    def update_status(self, authorization: CardAuthorization, new_status: str, reason: Optional[str] = None) -> None:
        old_status = authorization.status
        authorization.status = self.enumerators.get(CardAuthorizationStatus, new_status)
        authorization.updated_at = func.now()
        record_status_event(
            self.session,
            CardAuthorizationStatusEvent,
            "card_authorization",
            authorization,
            old_status,
            authorization.status,
            reason,
        )

    def list_expired_authorization_ids(self) -> List[str]:
        """authorization_id das APPROVED com expires_at já passado (job expire_authorizations)."""
        rows = (
            self.session.query(CardAuthorization.authorization_id)
            .join(CardAuthorization.status)
            .filter(
                CardAuthorizationStatus.enumerator == CardAuthorizationStatus.APPROVED,
                CardAuthorization.expires_at <= func.now(),
            )
            .order_by(CardAuthorization.id)
            .all()
        )
        return [row.authorization_id for row in rows]

    def get_event(self, event_type: str, external_id: str) -> Optional[CardAuthorizationEvent]:
        return (
            self.session.query(CardAuthorizationEvent)
            .filter(CardAuthorizationEvent.type == event_type, CardAuthorizationEvent.external_id == external_id)
            .first()
        )

    def add_event(
        self, authorization: CardAuthorization, event_type: str, amount: int, external_id: Optional[str] = None
    ) -> CardAuthorizationEvent:
        event = CardAuthorizationEvent()
        event.card_authorization = authorization
        event.type = event_type
        event.amount = amount
        event.external_id = external_id
        authorization.updated_at = func.now()
        self.session.add(event)
        return event