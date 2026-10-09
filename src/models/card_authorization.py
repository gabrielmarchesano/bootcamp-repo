from uuid import uuid4

from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey, func, Identity, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.types import PgEnum
from models.card_authorization_status import CardAuthorizationStatus


class CardAuthorization(Base):
    """Autorização = HOLD (débito) ou reserva de limite (crédito).

    Guarda os TOTAIS correntes. Cada movimento financeiro que os mudou é uma
    linha em card_authorization_event — o enumerador de eventos da QI.
    """

    __tablename__ = "card_authorization"

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"

    # Motivos de recusa (denial_reason)
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    INSUFFICIENT_LIMIT = "INSUFFICIENT_LIMIT"
    CARD_NOT_ACTIVE = "CARD_NOT_ACTIVE"
    ACCOUNT_NOT_ACTIVE = "ACCOUNT_NOT_ACTIVE"
    WALLET_NOT_ACTIVE = "WALLET_NOT_ACTIVE"
    FUNCTION_NOT_SUPPORTED = "FUNCTION_NOT_SUPPORTED"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    authorization_id = Column(String, nullable=False, unique=True)
    card_id = Column(BigInteger, ForeignKey("card.id"), nullable=False)
    account_id = Column(BigInteger, ForeignKey("account.id"), nullable=False)
    function = Column(PgEnum("enum_card_function"), nullable=False)
    amount = Column(BigInteger, nullable=False)
    authorized_amount = Column(BigInteger, nullable=False)
    captured_amount = Column(BigInteger, nullable=False)
    refunded_amount = Column(BigInteger, nullable=False)
    installment_count = Column(SmallInteger, nullable=False)
    merchant_name = Column(String)
    mcc = Column(CHAR(4))
    status_id = Column(SmallInteger, ForeignKey(CardAuthorizationStatus.id), nullable=False)
    response_code = Column(CHAR(2), nullable=False)
    denial_reason = Column(PgEnum("enum_denial_reason"))
    approval_code = Column(CHAR(6))
    expires_at = Column(DateTime(timezone=True))
    response_payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    status = relationship("CardAuthorizationStatus", foreign_keys=[status_id], lazy="selectin")
    card = relationship("Card", lazy="selectin")
    status_events = relationship(
        "CardAuthorizationStatusEvent",
        back_populates="card_authorization",
        order_by="CardAuthorizationStatusEvent.id",
        lazy="select",
    )
    events = relationship(
        "CardAuthorizationEvent", back_populates="card_authorization", order_by="CardAuthorizationEvent.id", lazy="select"
    )