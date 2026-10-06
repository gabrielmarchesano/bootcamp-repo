from sqlalchemy import CHAR, Boolean, Column, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.card_status import CardStatus


class Card(Base):
    """O instrumento. Quem tem limite é a carteira (wallet_id); cartão só de
    débito não tem carteira e debita a conta, como o pré-pago da QI."""

    __tablename__ = "card"

    # Tipos (QI card type)
    VIRTUAL = "VIRTUAL"
    PLASTIC = "PLASTIC"

    # Funções
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
    MULTIPLE = "MULTIPLE"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    account_id = Column(UUID(as_uuid=True), ForeignKey("account.id"), nullable=False)
    wallet_id = Column(UUID(as_uuid=True), ForeignKey("credit_wallet.id"))
    type = Column(String, nullable=False)
    pan_token = Column(String, nullable=False, unique=True)
    last4 = Column(CHAR(4), nullable=False)
    brand = Column(String, nullable=False)
    functions = Column(String, nullable=False)
    card_name = Column(String(15))
    printed_name = Column(String(26), nullable=False)
    contactless_enabled = Column(Boolean)
    activation_code_hash = Column(CHAR(64))
    status_id = Column(SmallInteger, ForeignKey(CardStatus.id), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    status = relationship("CardStatus", foreign_keys=[status_id], lazy="selectin")
    wallet = relationship("CreditWallet", lazy="selectin")
    status_events = relationship("CardStatusEvent", back_populates="card", order_by="CardStatusEvent.id", lazy="select")

    def supports(self, function: str) -> bool:
        return self.functions == Card.MULTIPLE or self.functions == function