from uuid import uuid4

from sqlalchemy import CHAR, BigInteger, Column, DateTime, ForeignKey, func, Identity, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.types import PgEnum


class InvoiceItem(Base):
    __tablename__ = "invoice_item"

    PURCHASE = "PURCHASE"
    PURCHASE_REFUND = "PURCHASE_REFUND"
    REVOLVING_CHARGE = "REVOLVING_CHARGE"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    invoice_id = Column(BigInteger, ForeignKey("invoice.id"), nullable=False)
    card_authorization_id = Column(BigInteger, ForeignKey("card_authorization.id"))
    type = Column(PgEnum("enum_invoice_item_type"), nullable=False)
    amount = Column(BigInteger, nullable=False)
    installment_number = Column(SmallInteger, nullable=False)
    installment_total = Column(SmallInteger, nullable=False)
    description = Column(String)
    idempotency_key = Column(String, unique=True)  # só encargo (REVOLVING_CHARGE)
    request_hash = Column(CHAR(64))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    invoice = relationship("Invoice", back_populates="items")