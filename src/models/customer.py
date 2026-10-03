from sqlalchemy import CHAR, BigInteger, Boolean, Column, Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.kyc_status import KycStatus

class Customer(Base):
    __tablename__ = "customer"
 
    # Tipos de cliente (classificação: não muda, fica como texto + CHECK)
    INDIVIDUAL = "INDIVIDUAL"
    MEI = "MEI"
 
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    cpf = Column(CHAR(11), nullable=False, unique=True)
    name = Column(String, nullable=False)
    birth_date = Column(Date, nullable=False)
    type = Column(String, nullable=False)
    cnpj = Column(CHAR(14), unique=True)
    annual_revenue = Column(BigInteger, nullable=False)
    revenue_reference_date = Column(Date, nullable=False, server_default=func.current_date())
    microcredit_eligible = Column(Boolean, nullable=False)
    kyc_status_id = Column(SmallInteger, ForeignKey(KycStatus.id), nullable=False)
    is_pep = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
 
    kyc_status = relationship("KycStatus", foreign_keys=[kyc_status_id], lazy="selectin")
    account = relationship("Account", back_populates="customer", uselist=False, lazy="selectin")
 