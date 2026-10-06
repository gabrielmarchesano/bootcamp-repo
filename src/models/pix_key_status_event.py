from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.pix_key_status import PixKeyStatus


class PixKeyStatusEvent(Base):
    """Uma linha por mudança de status da chave Pix: de onde, para onde, quando e por quê.

    Append-only no banco (trigger). Quem grava é o repository, no mesmo
    método que muda o status — não existe mudança de status sem rastro.
    """

    __tablename__ = "pix_key_status_event"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    pix_key_id = Column(UUID(as_uuid=True), ForeignKey("pix_key.id"), nullable=False)
    from_status_id = Column(SmallInteger, ForeignKey(PixKeyStatus.id))  # nulo ao nascer
    to_status_id = Column(SmallInteger, ForeignKey(PixKeyStatus.id), nullable=False)
    reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    pix_key = relationship("PixKey", back_populates="status_events")
    from_status = relationship("PixKeyStatus", foreign_keys=[from_status_id], lazy="selectin")
    to_status = relationship("PixKeyStatus", foreign_keys=[to_status_id], lazy="selectin")