from sqlalchemy import CHAR, BigInteger, Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base


class Account(Base):
    __tablename__ = "account"

    # Tipos
    CUSTOMER = "CUSTOMER"
    INTERNAL = "INTERNAL"

    # Status
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"

    # Contas internas (seed do database.sql)
    LOAN_PORTFOLIO = "LOAN_PORTFOLIO"
    ORIGINATION_FEE_REVENUE = "ORIGINATION_FEE_REVENUE"
    INTEREST_REVENUE = "INTEREST_REVENUE"
    FEE_REVENUE = "FEE_REVENUE"
    SPI_SETTLEMENT = "SPI_SETTLEMENT"
    STR_SETTLEMENT = "STR_SETTLEMENT"
    CARD_SETTLEMENT = "CARD_SETTLEMENT"

    DEFAULT_BRANCH = "0001"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    type = Column(String, nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customer.id"), unique=True)
    internal_code = Column(String, unique=True)
    branch = Column(CHAR(4))
    number = Column(String, unique=True)
    status = Column(String, nullable=False)
    status_reason = Column(String)
    balance = Column(BigInteger)
    held_balance = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    customer = relationship("Customer", back_populates="account", lazy="selectin")

    @property
    def available_balance(self) -> int:
        return self.balance - self.held_balance
