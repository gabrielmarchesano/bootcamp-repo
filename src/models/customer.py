from sqlalchemy import CHAR, BigInteger, Boolean, Column, Date, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base


class Customer(Base):
    __tablename__ = "customer"

    # Tipos de cliente
    INDIVIDUAL = "INDIVIDUAL"
    MEI = "MEI"

    # Status de KYC
    KYC_PENDING = "PENDING"
    KYC_APPROVED = "APPROVED"
    KYC_REJECTED = "REJECTED"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    cpf = Column(CHAR(11), nullable=False, unique=True)
    name = Column(String, nullable=False)
    birth_date = Column(Date, nullable=False)
    type = Column(String, nullable=False)
    cnpj = Column(CHAR(14), unique=True)
    annual_revenue = Column(BigInteger, nullable=False)
    revenue_reference_date = Column(Date, nullable=False, server_default=func.current_date())
    microcredit_eligible = Column(Boolean, nullable=False)
    kyc_status = Column(String, nullable=False)
    is_pep = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    account = relationship("Account", back_populates="customer", uselist=False, lazy="selectin")
