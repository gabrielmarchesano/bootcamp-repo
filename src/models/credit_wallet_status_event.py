from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.credit_wallet_status import CreditWalletStatus


class CreditWalletStatusEvent(Base):
    """Uma linha por mudança de status da carteira: de onde, para onde, quando e por quê.

    Append-only no banco (trigger). Quem grava é o repository, no mesmo
    método que muda o status — não existe mudança de status sem rastro.
    """

    __tablename__ = "credit_wallet_status_event"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    credit_wallet_id = Column(UUID(as_uuid=True), ForeignKey("credit_wallet.id"), nullable=False)
    from_status_id = Column(SmallInteger, ForeignKey(CreditWalletStatus.id))  # nulo ao nascer
    to_status_id = Column(SmallInteger, ForeignKey(CreditWalletStatus.id), nullable=False)
    reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    credit_wallet = relationship("CreditWallet", back_populates="status_events")
    from_status = relationship("CreditWalletStatus", foreign_keys=[from_status_id], lazy="selectin")
    to_status = relationship("CreditWalletStatus", foreign_keys=[to_status_id], lazy="selectin")