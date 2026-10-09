from uuid import uuid4

from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey, func, Identity, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.types import PgEnum
from models.incoming_transfer_status import IncomingTransferStatus


class IncomingTransfer(Base):
    __tablename__ = "incoming_transfer"

    # Trilhos (classificação: não muda, fica como texto + CHECK)
    SPI = "SPI"
    STR = "STR"

    # Tipos de Pix de entrada (QI pix_transfer_type de incoming_pix)
    PIX_KEY = "KEY"
    PIX_MANUAL = "MANUAL"
    PIX_STATIC_QR_CODE = "STATIC_QR_CODE"
    PIX_DYNAMIC_QR_CODE = "DYNAMIC_QR_CODE"
    PIX_REVERSAL = "REVERSAL"  # devolução de um Pix que NÓS enviamos
    
    # Os status moram em IncomingTransferStatus (tabela incoming_transfer_status).

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    rail = Column(PgEnum("enum_transfer_rail"), nullable=False)
    pix_transfer_type = Column(PgEnum("enum_pix_transfer_type"))
    external_id = Column(String, nullable=False)
    destination_account_id = Column(BigInteger, ForeignKey("account.id"))
    amount = Column(BigInteger, nullable=False)
    sender_name = Column(String)
    sender_document = Column(String)
    sender_ispb = Column(CHAR(8))
    receiver_pix_key = Column(String(77))
    pix_message = Column(String(140))
    original_transfer_id = Column(BigInteger, ForeignKey("transfer.id"))
    status_id = Column(SmallInteger, ForeignKey(IncomingTransferStatus.id), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    status = relationship("IncomingTransferStatus", foreign_keys=[status_id], lazy="selectin")
    original_transfer = relationship("Transfer", foreign_keys=[original_transfer_id], lazy="select")

    __table_args__ = (UniqueConstraint("rail", "external_id"),)