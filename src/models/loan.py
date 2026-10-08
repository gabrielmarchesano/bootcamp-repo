from uuid import uuid4

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.installment_status import InstallmentStatus
from models.loan_status import LoanStatus


class Loan(Base):
    """Contrato de microcrédito. Três papéis, três colunas:

    • customer_id          tomador: o CPF ou CNPJ que assina
    • account_id           conta do tomador que recebe o desembolso e paga
    • exposure_customer_id patrimônio que responde (= dono da credit_line)

    As três FKs compostas do banco (fk_loan_account, fk_loan_exposure,
    fk_loan_credit_line) recusam qualquer combinação incoerente.
    """

    __tablename__ = "loan"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    account_id = Column(BigInteger, ForeignKey("account.id"), nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customer.id"), nullable=False)
    exposure_customer_id = Column(BigInteger, nullable=False)
    credit_line_id = Column(BigInteger, ForeignKey("credit_line.id"), nullable=False)
    credit_line_version = Column(Integer, nullable=False)
    idempotency_key = Column(String, nullable=False, unique=True)
    request_hash = Column(CHAR(64), nullable=False)
    principal_amount = Column(BigInteger, nullable=False)
    installment_count = Column(SmallInteger, nullable=False)
    term_days = Column(SmallInteger, nullable=False)
    monthly_interest_rate = Column(Numeric(9, 6), nullable=False)
    effective_fee_rate = Column(Numeric(9, 6), nullable=False)
    origination_fee_amount = Column(BigInteger, nullable=False)
    net_amount = Column(BigInteger, nullable=False)
    effective_cost_monthly = Column(Numeric(9, 6), nullable=False)
    effective_cost_annual = Column(Numeric(9, 6), nullable=False)
    purpose = Column(String, nullable=False)
    sfn_debt_declaration = Column(Boolean, nullable=False)
    outstanding_principal = Column(BigInteger, nullable=False)
    status_id = Column(SmallInteger, ForeignKey(LoanStatus.id), nullable=False)
    contracted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    paid_off_at = Column(DateTime(timezone=True))

    status = relationship("LoanStatus", foreign_keys=[status_id], lazy="selectin")
    account = relationship("Account", foreign_keys=[account_id], lazy="select")
    customer = relationship("Customer", foreign_keys=[customer_id], lazy="select")
    credit_line = relationship("CreditLine", foreign_keys=[credit_line_id], lazy="select")
    installments = relationship(
        "Installment", back_populates="loan", order_by="Installment.number", lazy="select"
    )
    status_events = relationship(
        "LoanStatusEvent", back_populates="loan", order_by="LoanStatusEvent.id", lazy="select"
    )


class LoanStatusEvent(Base):
    __tablename__ = "loan_status_event"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    loan_id = Column(BigInteger, ForeignKey("loan.id"), nullable=False)
    from_status_id = Column(SmallInteger, ForeignKey(LoanStatus.id))  # nulo ao nascer
    to_status_id = Column(SmallInteger, ForeignKey(LoanStatus.id), nullable=False)
    reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    loan = relationship("Loan", back_populates="status_events")
    from_status = relationship("LoanStatus", foreign_keys=[from_status_id], lazy="selectin")
    to_status = relationship("LoanStatus", foreign_keys=[to_status_id], lazy="selectin")


class Installment(Base):
    __tablename__ = "installment"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    loan_id = Column(BigInteger, ForeignKey("loan.id"), nullable=False)
    number = Column(SmallInteger, nullable=False)
    due_date = Column(Date, nullable=False)
    principal_amount = Column(BigInteger, nullable=False)
    interest_amount = Column(BigInteger, nullable=False)
    paid_amount = Column(BigInteger, nullable=False, server_default="0")
    status_id = Column(SmallInteger, ForeignKey(InstallmentStatus.id), nullable=False)
    days_overdue = Column(Integer, nullable=False, server_default="0")
    paid_at = Column(DateTime(timezone=True))

    status = relationship("InstallmentStatus", foreign_keys=[status_id], lazy="selectin")
    loan = relationship("Loan", back_populates="installments")
    status_events = relationship(
        "InstallmentStatusEvent", back_populates="installment", order_by="InstallmentStatusEvent.id", lazy="select"
    )

    # total_amount é coluna GERADA no banco (principal + juros); aqui é conta.
    @property
    def total_amount(self) -> int:
        return self.principal_amount + self.interest_amount

    @property
    def remaining_amount(self) -> int:
        return max(self.total_amount - self.paid_amount, 0)


class InstallmentStatusEvent(Base):
    __tablename__ = "installment_status_event"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    installment_id = Column(BigInteger, ForeignKey("installment.id"), nullable=False)
    from_status_id = Column(SmallInteger, ForeignKey(InstallmentStatus.id))
    to_status_id = Column(SmallInteger, ForeignKey(InstallmentStatus.id), nullable=False)
    reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    installment = relationship("Installment", back_populates="status_events")
    from_status = relationship("InstallmentStatus", foreign_keys=[from_status_id], lazy="selectin")
    to_status = relationship("InstallmentStatus", foreign_keys=[to_status_id], lazy="selectin")


class LoanPayment(Base):
    __tablename__ = "loan_payment"

    MANUAL = "MANUAL"
    AUTO_COLLECTION = "AUTO_COLLECTION"

    REDUCE_TERM = "REDUCE_TERM"
    REDUCE_INSTALLMENT = "REDUCE_INSTALLMENT"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    loan_id = Column(BigInteger, ForeignKey("loan.id"), nullable=False)
    idempotency_key = Column(String, unique=True)
    request_hash = Column(CHAR(64))
    source = Column(String, nullable=False)
    mode = Column(String)
    amount = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    loan = relationship("Loan", lazy="select")
    allocations = relationship("PaymentAllocation", back_populates="payment", lazy="select")


class PaymentAllocation(Base):
    """Como cada pagamento foi alocado nas parcelas (antecipação a valor presente)."""

    __tablename__ = "payment_allocation"

    payment_id = Column(BigInteger, ForeignKey("loan_payment.id"), primary_key=True)
    installment_id = Column(BigInteger, ForeignKey("installment.id"), primary_key=True)
    principal_amount = Column(BigInteger, nullable=False)
    interest_amount = Column(BigInteger, nullable=False)
    prepayment_discount = Column(BigInteger, nullable=False, server_default="0")

    payment = relationship("LoanPayment", back_populates="allocations")
    installment = relationship("Installment", lazy="select")
