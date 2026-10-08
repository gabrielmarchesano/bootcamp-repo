from sqlalchemy import Column, SmallInteger, String

from models.base import Base


class LoanStatus(Base):
    """Status do contrato de microcrédito (tabela loan_status)."""

    __tablename__ = "loan_status"

    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"

    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
