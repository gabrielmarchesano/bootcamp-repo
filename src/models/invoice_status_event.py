from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, func, Identity, SmallInteger, String
from sqlalchemy.orm import relationship

from models.base import Base
from models.invoice_status import InvoiceStatus


class InvoiceStatusEvent(Base):
    """Uma linha por mudança de status da fatura: de onde, para onde, quando e por quê.

    Append-only no banco (trigger). Quem grava é o repository, no mesmo
    método que muda o status — não existe mudança de status sem rastro.
    """

    __tablename__ = "invoice_status_event"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    invoice_id = Column(BigInteger, ForeignKey("invoice.id"), nullable=False)
    from_status_id = Column(SmallInteger, ForeignKey(InvoiceStatus.id))  # nulo ao nascer
    to_status_id = Column(SmallInteger, ForeignKey(InvoiceStatus.id), nullable=False)
    reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    invoice = relationship("Invoice", back_populates="status_events")
    from_status = relationship("InvoiceStatus", foreign_keys=[from_status_id], lazy="selectin")
    to_status = relationship("InvoiceStatus", foreign_keys=[to_status_id], lazy="selectin")