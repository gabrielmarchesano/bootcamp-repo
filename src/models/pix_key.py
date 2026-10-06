from sqlalchemy import Column, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
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

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    account_id = Column(UUID(as_uuid=True), ForeignKey("account.id"), nullable=False)
    key_type = Column(String, nullable=False)
    key_value = Column(String(77), nullable=False)
    status_id = Column(SmallInteger, ForeignKey(PixKeyStatus.id), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    account = relationship("Account", lazy="selectin")
    status = relationship("PixKeyStatus", foreign_keys=[status_id], lazy="selectin")
    status_events = relationship(
        "PixKeyStatusEvent", back_populates="pix_key", order_by="PixKeyStatusEvent.id", lazy="select"
    )