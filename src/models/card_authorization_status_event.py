from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, func, Identity, SmallInteger, String
from sqlalchemy.orm import relationship

from models.base import Base
from models.card_authorization_status import CardAuthorizationStatus


class CardAuthorizationStatusEvent(Base):
    """Uma linha por mudança de status da autorização: de onde, para onde, quando e por quê.

    Append-only no banco (trigger). Quem grava é o repository, no mesmo
    método que muda o status — não existe mudança de status sem rastro.
    """

    __tablename__ = "card_authorization_status_event"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    card_authorization_id = Column(BigInteger, ForeignKey("card_authorization.id"), nullable=False)
    from_status_id = Column(SmallInteger, ForeignKey(CardAuthorizationStatus.id))  # nulo ao nascer
    to_status_id = Column(SmallInteger, ForeignKey(CardAuthorizationStatus.id), nullable=False)
    reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    card_authorization = relationship("CardAuthorization", back_populates="status_events")
    from_status = relationship("CardAuthorizationStatus", foreign_keys=[from_status_id], lazy="selectin")
    to_status = relationship("CardAuthorizationStatus", foreign_keys=[to_status_id], lazy="selectin")