from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.transfer_status import TransferStatus


class TransferStatusEvent(Base):
    """Uma linha por mudança de status da transferência: de onde, para onde, quando e por quê.

    A coluna `transfer.status_id` responde ONDE está agora; esta tabela
    responde desde quando e por qual caminho. Append-only no banco
    (trigger): ninguém edita nem apaga um evento.

    Não crie evento à mão: quem grava é o repository, no mesmo método
    que muda o status. Assim não existe mudança de status sem rastro.
    """

    __tablename__ = "transfer_status_event"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    transfer_id = Column(UUID(as_uuid=True), ForeignKey("transfer.id"), nullable=False)
    from_status_id = Column(SmallInteger, ForeignKey(TransferStatus.id))  # nulo ao nascer
    to_status_id = Column(SmallInteger, ForeignKey(TransferStatus.id), nullable=False)
    reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    transfer = relationship("Transfer", back_populates="status_events")
    from_status = relationship("TransferStatus", foreign_keys=[from_status_id], lazy="selectin")
    to_status = relationship("TransferStatus", foreign_keys=[to_status_id], lazy="selectin")