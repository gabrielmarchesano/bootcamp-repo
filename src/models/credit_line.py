from uuid import uuid4

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, Integer, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base


class CreditLine(Base):
    """Linha de microcrédito do PATRIMÔNIO (não da conta, não do CNPJ).

    `customer_id` é sempre a raiz do patrimônio: a PF (que também cobre o
    EI/MEI dela) ou a sociedade. O banco garante com fk_credit_line_root.
    Mutável sob FOR UPDATE: é o lock dela que serializa contratações do
    mesmo patrimônio vindas de contas e CNPJs diferentes.
    """

    __tablename__ = "credit_line"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    customer_id = Column(BigInteger, ForeignKey("customer.id"), nullable=False, unique=True)
    version = Column(Integer, nullable=False)
    total_limit = Column(BigInteger, nullable=False)
    available_limit = Column(BigInteger, nullable=False)
    monthly_interest_rate = Column(Numeric(9, 6), nullable=False)
    origination_fee_rate = Column(Numeric(9, 6), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    customer = relationship("Customer", foreign_keys=[customer_id], lazy="select")


class CreditLineVersion(Base):
    """Histórico append-only de cada PUT da IF (auditoria)."""

    __tablename__ = "credit_line_version"

    credit_line_id = Column(BigInteger, ForeignKey("credit_line.id"), primary_key=True)
    version = Column(Integer, primary_key=True)
    total_limit = Column(BigInteger, nullable=False)
    monthly_interest_rate = Column(Numeric(9, 6), nullable=False)
    origination_fee_rate = Column(Numeric(9, 6), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
