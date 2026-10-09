from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, func, Identity, String
from sqlalchemy.orm import relationship

from models.base import Base
from models.types import PgEnum


class CardAuthorizationEvent(Base):
    """Um movimento financeiro da autorização. Enumerador da QI, 1 para 1.

    Diferente do *_status_event: aquele conta por onde o STATUS passou;
    este conta o DINHEIRO (quanto foi autorizado, capturado, estornado).
    Append-only. `external_id` é o id da rede: repetir a mesma captura
    bate no UNIQUE (type, external_id).
    """

    __tablename__ = "card_authorization_event"

    AUTHORIZATION = "AUTHORIZATION"
    INCREMENTAL_AUTHORIZATION = "INCREMENTAL_AUTHORIZATION"
    REVERSAL = "REVERSAL"
    PARTIAL_REVERSAL = "PARTIAL_REVERSAL"
    EXPIRATION = "EXPIRATION"
    CAPTURE = "CAPTURE"
    REFUND = "REFUND"
    PARTIAL_REFUND = "PARTIAL_REFUND"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    card_authorization_id = Column(BigInteger, ForeignKey("card_authorization.id"), nullable=False)
    type = Column(PgEnum("enum_card_auth_event_type"), nullable=False)
    amount = Column(BigInteger, nullable=False)
    external_id = Column(String)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    card_authorization = relationship("CardAuthorization", back_populates="events")
