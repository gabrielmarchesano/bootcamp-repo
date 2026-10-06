from typing import List, Optional
from uuid import UUID

from sqlalchemy import func

from database import Context
from models import PixKey, PixKeyInquiry, PixKeyStatus, PixKeyStatusEvent
from repositories.enumerator_repository import EnumeratorRepository
from repositories.status_event_recorder import record_status_event


class PixKeyRepository:
    """Chaves Pix da casa e as consultas ao DICT feitas pelas nossas contas."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

    def create(self, account_id: UUID, key_type: str, key_value: str) -> PixKey:
        pix_key = PixKey()
        pix_key.account_id = account_id
        pix_key.key_type = key_type
        pix_key.key_value = key_value
        pix_key.status = self.enumerators.get(PixKeyStatus, PixKeyStatus.ACTIVE)

        self.session.add(pix_key)
        record_status_event(self.session, PixKeyStatusEvent, "pix_key", pix_key, None, pix_key.status, None)
        self.session.flush()
        return pix_key

    def get_by_id(self, pix_key_id: UUID) -> Optional[PixKey]:
        return self.session.query(PixKey).filter(PixKey.id == pix_key_id).first()

    def get_active_by_value(self, key_value: str) -> Optional[PixKey]:
        return (
            self.session.query(PixKey)
            .join(PixKey.status)
            .filter(PixKey.key_value == key_value, PixKeyStatus.enumerator == PixKeyStatus.ACTIVE)
            .first()
        )

    def list_active(self, account_id: UUID) -> List[PixKey]:
        return (
            self.session.query(PixKey)
            .join(PixKey.status)
            .filter(PixKey.account_id == account_id, PixKeyStatus.enumerator == PixKeyStatus.ACTIVE)
            .order_by(PixKey.created_at)
            .all()
        )

    def delete(self, pix_key: PixKey, reason: Optional[str]) -> None:
        old_status = pix_key.status
        pix_key.status = self.enumerators.get(PixKeyStatus, PixKeyStatus.DELETED)
        pix_key.updated_at = func.now()
        record_status_event(self.session, PixKeyStatusEvent, "pix_key", pix_key, old_status, pix_key.status, reason)

    # ── consultas ao DICT ───────────────────────────────────────────

    def create_inquiry(self, **fields) -> PixKeyInquiry:
        inquiry = PixKeyInquiry()
        for name, value in fields.items():
            setattr(inquiry, name, value)
        self.session.add(inquiry)
        self.session.flush()
        return inquiry

    def get_inquiry(self, account_id: UUID, end_to_end_id: str) -> Optional[PixKeyInquiry]:
        return (
            self.session.query(PixKeyInquiry)
            .filter(PixKeyInquiry.account_id == account_id, PixKeyInquiry.end_to_end_id == end_to_end_id)
            .first()
        )