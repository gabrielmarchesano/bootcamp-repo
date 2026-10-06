from sqlalchemy import CHAR, BigInteger, Boolean, Column, Date, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.transfer_status import TransferStatus


class Transfer(Base):
    __tablename__ = "transfer"

    # Métodos (classificação: não muda, fica como texto + CHECK)
    TEF = "TEF"
    PIX = "PIX"
    TED = "TED"

    # Tipos de Pix de saída (QI pix_transfer_type). QR code fica para a v2.
    PIX_KEY = "KEY"
    PIX_MANUAL = "MANUAL"
    PIX_REVERSAL = "REVERSAL"

    # Motivos de devolução (QI reversal_reason)
    REVERSAL_REASONS = ("CLIENT_REQUEST", "RECONCILIATION")
    # Os status moram em TransferStatus (tabela transfer_status).

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    idempotency_key = Column(String, nullable=False, unique=True)
    request_hash = Column(CHAR(64), nullable=False)
    source_account_id = Column(UUID(as_uuid=True), ForeignKey("account.id"), nullable=False)
    method = Column(String, nullable=False)
    pix_transfer_type = Column(String)
    amount = Column(BigInteger, nullable=False)
    fee = Column(BigInteger, nullable=False)
    status_id = Column(SmallInteger, ForeignKey(TransferStatus.id), nullable=False)
    on_us = Column(Boolean, nullable=False)
    destination_account_id = Column(UUID(as_uuid=True), ForeignKey("account.id"))
    pix_key = Column(String)
    pix_key_inquiry_id = Column(UUID(as_uuid=True), unique=True)
    destination_ispb = Column(CHAR(8))
    destination_branch = Column(String)
    destination_account = Column(String)
    destination_account_digit = Column(CHAR(1))
    destination_account_type = Column(String)
    destination_document = Column(String)
    destination_name = Column(String)
    pix_message = Column(String(140))
    original_incoming_transfer_id = Column(UUID(as_uuid=True), ForeignKey("incoming_transfer.id"))
    reversal_reason = Column(String)
    end_to_end_id = Column(String, unique=True)
    str_control_number = Column(String, unique=True)
    scheduled_for = Column(Date)
    failure_code = Column(String(20))
    failure_reason = Column(String)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True))

    
    status = relationship("TransferStatus", foreign_keys=[status_id], lazy="selectin")
    status_events = relationship(
        "TransferStatusEvent",
        back_populates="transfer",
        order_by="TransferStatusEvent.id",
        lazy="select",
    )