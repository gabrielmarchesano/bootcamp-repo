from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, Integer, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.outbox_event_status import OutboxEventStatus


class OutboxEvent(Base):
    """Evento para a IF, gravado na MESMA transação do fato que ele conta.

    Se a transação dá rollback, o evento some junto; se dá commit, ele
    existe. Não há como a IF ser avisada de algo que não aconteceu. Quem
    envia é o job dispatch_outbox_events (src/jobs).
    """

    __tablename__ = "outbox_event"

    ACCOUNT_OPENED = "baas.account.opened"
    ACCOUNT_STATUS_CHANGED = "baas.account.status_change"
    OUTGOING_TEF = "baas.tef.outgoing_tef"
    OUTGOING_PIX = "baas.pix_transfer.outgoing_pix"
    INCOMING_PIX = "baas.pix_transfer.incoming_pix"
    OUTGOING_TED = "baas.ted.outgoing_ted"
    INCOMING_TED = "baas.ted.incoming_ted"
    PIX_KEY_STATUS_CHANGED = "baas.pix_key.status_change"
    CREDIT_WALLET_STATUS_CHANGED = "baas.credit_wallet.status_change"
    CARD_STATUS_CHANGED = "baas.card.status_change"
    CARD_AUTHORIZATION = "baas.card.authorization"
    CREDIT_LINE_CHANGED = "baas.credit_line.change"
    LOAN_CONTRACTED = "baas.loan.contracted"
    LOAN_PAYMENT = "baas.loan.payment"
    LOAN_PAID_OFF = "baas.loan.paid_off"
    INSTALLMENT_OVERDUE = "baas.installment.overdue"
    INVOICE_STATUS_CHANGED = "baas.invoice.status_change"
    INVOICE_PAYMENT = "baas.invoice.payment"
    INVOICE_CHARGE = "baas.invoice.charge"
 

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    type = Column(String, nullable=False)
    aggregate_type = Column(String, nullable=False)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False)
    payload = Column(JSONB, nullable=False)
    status_id = Column(SmallInteger, ForeignKey(OutboxEventStatus.id), nullable=False)
    attempts = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at = Column(DateTime(timezone=True))

    status = relationship("OutboxEventStatus", foreign_keys=[status_id], lazy="selectin")