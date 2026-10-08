from uuid import uuid4

from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, func, Identity, SmallInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.invoice_status import InvoiceStatus


class Invoice(Base):
    """Fatura da CARTEIRA (não do cartão). Uma por mês de fechamento."""

    __tablename__ = "invoice"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    wallet_id = Column(BigInteger, ForeignKey("credit_wallet.id"), nullable=False)
    reference_month = Column(Date, nullable=False)
    status_id = Column(SmallInteger, ForeignKey(InvoiceStatus.id), nullable=False)
    closing_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    total_amount = Column(BigInteger, nullable=False)
    paid_amount = Column(BigInteger, nullable=False)
    original_debt_amount = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    status = relationship("InvoiceStatus", foreign_keys=[status_id], lazy="selectin")
    wallet = relationship("CreditWallet", foreign_keys=[wallet_id], lazy="select")
    items = relationship("InvoiceItem", back_populates="invoice", order_by="InvoiceItem.created_at", lazy="select")
    status_events = relationship(
        "InvoiceStatusEvent", back_populates="invoice", order_by="InvoiceStatusEvent.id", lazy="select"
    )