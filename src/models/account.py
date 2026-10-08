from sqlalchemy import CHAR, BigInteger, Column, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.account_status import AccountStatus


class Account(Base):
    __tablename__ = "account"
 
    # Tipos (classificação: não muda, fica como texto + CHECK)
    CUSTOMER = "CUSTOMER"
    INTERNAL = "INTERNAL"
 
    # Os status moram em AccountStatus (tabela account_status).
 
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
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customer.id"))
    internal_code = Column(String, unique=True)
    branch = Column(CHAR(4))
    number = Column(String, unique=True)
    status_id = Column(SmallInteger, ForeignKey(AccountStatus.id), nullable=False)
    status_reason = Column(String)
    balance = Column(BigInteger)
    held_balance = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
 
    customer = relationship("Customer", back_populates="accounts", lazy="selectin")
 
    # Na tabela o status é um número; aqui, um objeto com `.enumerator`.
    # "selectin" (consulta separada) e não "joined": o lock da conta usa
    # FOR UPDATE, e o Postgres recusa FOR UPDATE em cima de LEFT JOIN.
    status = relationship("AccountStatus", foreign_keys=[status_id], lazy="selectin")
 
    # O caminho até o status atual. "select": só vai ao banco quando alguém
    # pede (o DTO do GET), e não a cada lock de conta numa transferência.
    # É uma relação de verdade (não viewonly) de propósito: é ela que faz o
    # SQLAlchemy gravar a conta ANTES do evento de nascimento, que aponta
    # para ela. Mexa aqui e o INSERT sai na ordem errada.
    status_events = relationship(
        "AccountStatusEvent",
        back_populates="account",
        order_by="AccountStatusEvent.id",
        lazy="select",
    )
 
    @property
    def available_balance(self) -> int:
        return self.balance - self.held_balance
 