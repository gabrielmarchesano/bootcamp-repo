from datetime import date, datetime
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, tuple_

from database import Context
from models import (
    Installment,
    InstallmentStatus,
    InstallmentStatusEvent,
    Loan,
    LoanPayment,
    LoanStatus,
    LoanStatusEvent,
    PaymentAllocation,
)
from repositories.enumerator_repository import EnumeratorRepository
from repositories.status_event_recorder import record_status_event


class LoanRepository:
    """Contrato, parcelas e pagamentos. Lock: depois da conta e da linha."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

    # ── contrato ─────────────────────────────────────────────────────

    def get_by_key(self, loan_key: UUID) -> Optional[Loan]:
        return self.session.query(Loan).filter(Loan.key == loan_key).first()

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[Loan]:
        return self.session.query(Loan).filter(Loan.idempotency_key == idempotency_key).first()

    def lock(self, loan_id: int) -> Optional[Loan]:
        return self.session.query(Loan).filter(Loan.id == loan_id).populate_existing().with_for_update().first()

    def create(self, fields: dict) -> Loan:
        loan = Loan()
        for name, value in fields.items():
            setattr(loan, name, value)
        loan.status = self.enumerators.get(LoanStatus, LoanStatus.ACTIVE)
        self.session.add(loan)
        record_status_event(self.session, LoanStatusEvent, "loan", loan, None, loan.status, None)
        self.session.flush()
        return loan

    def update_status(self, loan: Loan, new_status: str, reason: Optional[str] = None) -> None:
        old_status = loan.status
        loan.status = self.enumerators.get(LoanStatus, new_status)
        if new_status == LoanStatus.PAID_OFF:
            loan.paid_off_at = func.now()
        record_status_event(self.session, LoanStatusEvent, "loan", loan, old_status, loan.status, reason)

    def list_by_account(
        self, account_id: int, statuses: List[str], limit: int, after: Optional[Tuple[datetime, str]]
    ) -> List[Loan]:
        query = self.session.query(Loan).filter(Loan.account_id == account_id)
        if statuses:
            query = query.join(Loan.status).filter(LoanStatus.enumerator.in_(statuses))
        if after is not None:
            after_contracted_at, after_id = after
            query = query.filter(tuple_(Loan.contracted_at, Loan.id) < tuple_(after_contracted_at, int(after_id)))
        query = query.order_by(Loan.contracted_at.desc(), Loan.id.desc())
        return query.limit(limit + 1).all()

    # ── parcelas ─────────────────────────────────────────────────────

    def add_installment(self, loan: Loan, number: int, due_date: date, principal: int, interest: int) -> Installment:
        installment = Installment()
        installment.loan = loan
        installment.number = number
        installment.due_date = due_date
        installment.principal_amount = principal
        installment.interest_amount = interest
        installment.paid_amount = 0
        installment.days_overdue = 0
        installment.status = self.enumerators.get(InstallmentStatus, InstallmentStatus.OPEN)
        self.session.add(installment)
        record_status_event(
            self.session, InstallmentStatusEvent, "installment", installment, None, installment.status, None
        )
        return installment

    def lock_unpaid_installments(self, loan_id: int) -> List[Installment]:
        """Parcelas em aberto do contrato, da mais antiga à mais nova, travadas (por id)."""
        return (
            self.session.query(Installment)
            .join(Installment.status)
            .filter(Installment.loan_id == loan_id, InstallmentStatus.enumerator.in_(InstallmentStatus.UNPAID))
            .order_by(Installment.number)
            .populate_existing()
            .with_for_update(of=Installment)
            .all()
        )

    def list_due_loans(self, day: date) -> List[Tuple[int, int]]:
        """(loan_id, account_id) dos contratos com parcela em aberto vencida até `day`."""
        rows = (
            self.session.query(Loan.id, Loan.account_id)
            .join(Installment, Installment.loan_id == Loan.id)
            .join(InstallmentStatus, InstallmentStatus.id == Installment.status_id)
            .filter(InstallmentStatus.enumerator.in_(InstallmentStatus.UNPAID), Installment.due_date <= day)
            .distinct()
            .order_by(Loan.id)
            .all()
        )
        return [(row.id, row.account_id) for row in rows]

    def update_installment_status(self, installment: Installment, new_status: str, reason: Optional[str] = None):
        if installment.status.enumerator == new_status:
            return
        old_status = installment.status
        installment.status = self.enumerators.get(InstallmentStatus, new_status)
        if new_status == InstallmentStatus.PAID:
            installment.paid_at = func.now()
        record_status_event(
            self.session, InstallmentStatusEvent, "installment", installment, old_status, installment.status, reason
        )

    # ── pagamentos ───────────────────────────────────────────────────

    def get_payment_by_idempotency_key(self, idempotency_key: str) -> Optional[LoanPayment]:
        return self.session.query(LoanPayment).filter(LoanPayment.idempotency_key == idempotency_key).first()

    def add_payment(
        self, loan: Loan, source: str, amount: int, mode: Optional[str], idempotency_key=None, request_hash=None
    ) -> LoanPayment:
        payment = LoanPayment()
        payment.loan_id = loan.id
        payment.source = source
        payment.mode = mode
        payment.amount = amount
        payment.idempotency_key = idempotency_key
        payment.request_hash = request_hash
        self.session.add(payment)
        self.session.flush()
        return payment

    def add_allocation(self, payment: LoanPayment, installment: Installment, principal: int, interest: int, discount: int):
        allocation = PaymentAllocation()
        allocation.payment_id = payment.id
        allocation.installment_id = installment.id
        allocation.principal_amount = principal
        allocation.interest_amount = interest
        allocation.prepayment_discount = discount
        self.session.add(allocation)
        return allocation
