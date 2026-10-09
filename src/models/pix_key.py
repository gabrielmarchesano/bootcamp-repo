from uuid import uuid4

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, func, Identity, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.types import PgEnum
from models.pix_key_status import PixKeyStatus


class PixKey(Base):
    """Chave Pix de um cliente NOSSO. É o que o DICT mock consulta para
    resolver um Pix entre contas da casa (QI: Create/Delete/List Pix Key)."""

    __tablename__ = "pix_key"

    # Tipos de chave (classificação: não muda, fica como texto + CHECK)
    CPF = "CPF"
    CNPJ = "CNPJ"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    EVP = "EVP"  # chave aleatória

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    account_id = Column(BigInteger, ForeignKey("account.id"), nullable=False)
    key_type = Column(PgEnum("enum_pix_key_type"), nullable=False)
    key_value = Column(String(77), nullable=False)
    status_id = Column(SmallInteger, ForeignKey(PixKeyStatus.id), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    account = relationship("Account", lazy="selectin")
    status = relationship("PixKeyStatus", foreign_keys=[status_id], lazy="selectin")
    status_events = relationship(
        "PixKeyStatusEvent", back_populates="pix_key", order_by="PixKeyStatusEvent.id", lazy="select"
    )
