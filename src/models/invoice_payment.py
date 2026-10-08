from uuid import uuid4

from sqlalchemy import CHAR, BigInteger, Column, DateTime, ForeignKey, Identity, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base


class InvoicePayment(Base):
    """Pagamento de fatura: manual (Idempotency-Key) ou débito automático (um por fatura)."""

    __tablename__ = "invoice_payment"

    MANUAL = "MANUAL"
    AUTOPAY = "AUTOPAY"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    invoice_id = Column(BigInteger, ForeignKey("invoice.id"), nullable=False)
    idempotency_key = Column(String, unique=True)  # NULL no débito automático
    request_hash = Column(CHAR(64))
    source = Column(String, nullable=False)
    amount = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    invoice = relationship("Invoice", lazy="select")
