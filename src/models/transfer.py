from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, CHAR, Column, Date, DateTime, ForeignKey, func, Identity, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.types import PgEnum
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

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    idempotency_key = Column(String, nullable=False, unique=True)
    request_hash = Column(CHAR(64), nullable=False)
    source_account_id = Column(BigInteger, ForeignKey("account.id"), nullable=False)
    method = Column(PgEnum("enum_transfer_method"), nullable=False)
    pix_transfer_type = Column(PgEnum("enum_pix_transfer_type"))
    amount = Column(BigInteger, nullable=False)
    fee = Column(BigInteger, nullable=False)
    status_id = Column(SmallInteger, ForeignKey(TransferStatus.id), nullable=False)
    on_us = Column(Boolean, nullable=False)
    destination_account_id = Column(BigInteger, ForeignKey("account.id"))
    pix_key = Column(String)
    pix_key_inquiry_id = Column(BigInteger, ForeignKey("pix_key_inquiry.id"), unique=True)
    destination_ispb = Column(CHAR(8))
    destination_branch = Column(String)
    destination_account = Column(String)
    destination_account_digit = Column(CHAR(1))
    destination_account_type = Column(PgEnum("enum_external_account_type"))
    destination_document = Column(String)
    destination_name = Column(String)
    pix_message = Column(String(140))
    original_incoming_transfer_id = Column(BigInteger, ForeignKey("incoming_transfer.id"))
    reversal_reason = Column(PgEnum("enum_reversal_reason"))
    end_to_end_id = Column(String, unique=True)
    str_control_number = Column(String, unique=True)
    scheduled_for = Column(Date)
    failure_code = Column(String(20))
    failure_reason = Column(String)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True))

    
    status = relationship("TransferStatus", foreign_keys=[status_id], lazy="selectin")
    # Só para o DTO expor a key pública das pontas. "select": lido sob demanda,
    # nunca junto do FOR UPDATE.
    source_account = relationship("Account", foreign_keys=[source_account_id], lazy="select")
    # Não pode se chamar destination_account: esse nome é a coluna com o
    # número da conta externa (Pix manual / TED) e o relationship a sobrescreveria.
    destination_account_ref = relationship("Account", foreign_keys=[destination_account_id], lazy="select")
    original_incoming_transfer = relationship(
        "IncomingTransfer", foreign_keys=[original_incoming_transfer_id], lazy="select"
    )
    status_events = relationship(
        "TransferStatusEvent",
        back_populates="transfer",
        order_by="TransferStatusEvent.id",
        lazy="select",
    )