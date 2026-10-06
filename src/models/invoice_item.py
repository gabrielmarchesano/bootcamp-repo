from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base


class InvoiceItem(Base):
    __tablename__ = "invoice_item"

    PURCHASE = "PURCHASE"
    PURCHASE_REFUND = "PURCHASE_REFUND"
    REVOLVING_CHARGE = "REVOLVING_CHARGE"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoice.id"), nullable=False)
    card_authorization_id = Column(UUID(as_uuid=True), ForeignKey("card_authorization.id"))
    type = Column(String, nullable=False)
    amount = Column(BigInteger, nullable=False)
    installment_number = Column(SmallInteger, nullable=False)
    installment_total = Column(SmallInteger, nullable=False)
    description = Column(String)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    invoice = relationship("Invoice", back_populates="items")