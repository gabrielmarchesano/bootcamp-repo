from sqlalchemy import CHAR, BigInteger, Column, DateTime, ForeignKey, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.incoming_transfer_status import IncomingTransferStatus


class IncomingTransfer(Base):
    __tablename__ = "incoming_transfer"

    # Trilhos (classificação: não muda, fica como texto + CHECK)
    SPI = "SPI"
    STR = "STR"

    # Os status moram em IncomingTransferStatus (tabela incoming_transfer_status).

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    rail = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    destination_account_id = Column(UUID(as_uuid=True), ForeignKey("account.id"))
    amount = Column(BigInteger, nullable=False)
    sender_name = Column(String)
    sender_document = Column(String)
    sender_ispb = Column(CHAR(8))
    status_id = Column(SmallInteger, ForeignKey(IncomingTransferStatus.id), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    status = relationship("IncomingTransferStatus", foreign_keys=[status_id], lazy="selectin")

    __table_args__ = (UniqueConstraint("rail", "external_id"),)