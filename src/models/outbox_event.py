from sqlalchemy import BigInteger, Column, DateTime, Identity, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.base import Base


class OutboxEvent(Base):
    """Evento para a IF, gravado na MESMA transação do fato que ele conta.

    Se a transação dá rollback, o evento some junto; se dá commit, ele
    existe. Não há como a IF ser avisada de algo que não aconteceu. Quem
    envia é o job dispatch_outbox_events (próximo sprint).
    """

    __tablename__ = "outbox_event"

    ACCOUNT_OPENED = "ACCOUNT_OPENED"
    ACCOUNT_STATUS_CHANGED = "ACCOUNT_STATUS_CHANGED"
    TRANSFER_COMPLETED = "TRANSFER_COMPLETED"
    INCOMING_TRANSFER_CREDITED = "INCOMING_TRANSFER_CREDITED"
    INCOMING_TRANSFER_RETURNED = "INCOMING_TRANSFER_RETURNED"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    type = Column(String, nullable=False)
    aggregate_type = Column(String, nullable=False)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(String, nullable=False, server_default="PENDING")
    attempts = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at = Column(DateTime(timezone=True))
