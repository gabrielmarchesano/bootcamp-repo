from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from controllers.credit_line_controller import MPO_MAX_LIMIT
from dtos import LoanDTO
from errors import (
    AccountNotActive,
    AccountNotFound,
    AmountAboveDue,
    CustomerNotEligible,
    IdempotencyConflict,
    IdempotencyKeyRequired,
    InsufficientBalance,
    InsufficientCreditLimit,
    InvalidParameter,
    LoanAlreadyPaidOff,
    LoanNotFound,
    NoCreditLine,
    OutOfMpoRule,
    RegulatoryCapExceeded,
)
from models import (
    Account,
    AccountStatus,
    Installment,
    InstallmentStatus,
    LedgerEntry,
    Loan,
    LoanPayment,
    LoanStatus,
    OutboxEvent,
)
from repositories import (
    AccountRepository,
    CalendarRepository,
    CreditLineRepository,
    LedgerLeg,
    LedgerRepository,
    LoanRepository,
    OutboxRepository,
)
from utils.cursor import decode_cursor, encode_cursor
from utils.db_retry import retry_on_deadlock
from utils.idempotency import is_valid_idempotency_key, request_hash
from utils.ids import parse_uuid
from utils.loan_math import loan_terms, prepayment_discount

MPO_MIN_TERM_DAYS = 60
MPO_MAX_TERM_DAYS = 720


@dataclass
class Allocation:
    """Quanto de um pagamento caiu numa parcela, e em quê."""

    installment: Installment
    principal: int
    interest: int  # juros pagos em dinheiro
    discount: int  # juros perdoados pela antecipação (não é dinheiro)

    @property
    def cash(self) -> int:
        return self.principal + self.interest

    @property
    def credited(self) -> int:
        return self.principal + self.interest + self.discount


class LoanController(BaseController):
    """Contratação, consulta e pagamento do microcrédito.

    ────────────────────────────────────────────────────────────────
    ORDEM DE LOCK (a global): conta → linha do patrimônio → contrato → parcelas
    ────────────────────────────────────────────────────────────────
    O teto de R$ 21 mil é do PATRIMÔNIO: a PF e o EI/MEI dela, em contas
    diferentes, disputam a MESMA linha. É o lock da linha que serializa as
    duas contratações — a segunda lê o limite já reduzido pela primeira.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_repository = AccountRepository(self.context)
        self.credit_line_repository = CreditLineRepository(self.context)
        self.loan_repository = LoanRepository(self.context)
        self.ledger_repository = LedgerRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)
        self.calendar_repository = CalendarRepository(self.context)

    # ── simulação ────────────────────────────────────────────────────

    def simulate(self, raw_account_id: str, payload: dict) -> dict:
        """Mesmas contas da contratação, sem gravar nada e sem lock."""
        account = self._get_account_or_raise(raw_account_id)
        borrower = account.customer

        if not borrower.microcredit_eligible:
            raise CustomerNotEligible()

        line = self.credit_line_repository.get_by_customer(borrower.exposure_customer_id)
        if line is None:
            raise NoCreditLine()

        terms = self._terms(line, payload)
        return LoanDTO.simulation_to_dict(terms)

    # ── contratação + desembolso ─────────────────────────────────────

    @retry_on_deadlock()
    def create(self, raw_account_id: str, payload: dict, idempotency_key: str) -> Tuple[dict, bool]:
        """Contrata e desembolsa na mesma transação.

          1. idempotência (antes de tudo)
          2. tomador elegível e patrimônio com linha
          3. trava a conta e a linha do patrimônio (ordem global)
          4. idempotência DE NOVO, com o lock na mão
          5. limite disponível da linha e teto de R$ 21 mil do patrimônio
          6. contrato + parcelas + baixa do limite + desembolso e TAC no ledger
        """
        if not is_valid_idempotency_key(idempotency_key):
            raise IdempotencyKeyRequired()

        payload_hash = request_hash(payload)
        replay = self._find_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        unlocked = self._get_account_or_raise(raw_account_id)
        borrower = unlocked.customer

        if not borrower.microcredit_eligible:
            raise CustomerNotEligible()

        exposure_id = borrower.exposure_customer_id

        locked = self.account_repository.lock_customer_accounts([unlocked.id])
        account = locked.get(unlocked.id)
        if account is None:
            raise AccountNotFound(raw_account_id)

        line = self.credit_line_repository.lock_by_customer(exposure_id)
        if line is None:
            raise NoCreditLine()

        replay = self._find_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        if account.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(account.key, account.status.enumerator)

        amount = payload["amount"]
        if amount > line.available_limit:
            raise InsufficientCreditLimit(amount, line.available_limit)

        balance_after = self.credit_line_repository.microcredit_balance(exposure_id) + amount
        if balance_after > MPO_MAX_LIMIT:
            raise RegulatoryCapExceeded(balance_after, MPO_MAX_LIMIT)

        terms = self._terms(line, payload)

        try:
            loan = self.loan_repository.create(
                {
                    "account_id": account.id,
                    "customer_id": borrower.id,
                    "exposure_customer_id": exposure_id,
                    "credit_line_id": line.id,
                    "credit_line_version": line.version,
                    "idempotency_key": idempotency_key,
                    "request_hash": payload_hash,
                    "principal_amount": terms.principal_amount,
                    "installment_count": terms.installment_count,
                    "term_days": terms.term_days,
                    "monthly_interest_rate": terms.monthly_interest_rate,
                    "effective_fee_rate": terms.effective_fee_rate,
                    "origination_fee_amount": terms.origination_fee_amount,
                    "net_amount": terms.net_amount,
                    "effective_cost_monthly": terms.effective_cost_monthly,
                    "effective_cost_annual": terms.effective_cost_annual,
                    "purpose": payload["purpose"],
                    "sfn_debt_declaration": payload["sfn_debt_declaration"],
                    "outstanding_principal": terms.principal_amount,
                }
            )
        except IntegrityError:
            self.session.rollback()
            replay = self._find_replay(idempotency_key, payload_hash)
            if replay is not None:
                return replay, False
            raise

        for item in terms.installments:
            self.loan_repository.add_installment(
                loan, item.number, item.due_date, item.principal_amount, item.interest_amount
            )

        line.available_limit = line.available_limit - amount

        # Desembolso: a carteira de crédito da IF empresta o principal; a TAC
        # sai da conta do tomador para a receita. O líquido fica na conta.
        portfolio = self.account_repository.get_internal(Account.LOAN_PORTFOLIO)
        legs = [
            LedgerLeg(portfolio, -amount, LedgerEntry.DISBURSEMENT),
            LedgerLeg(account, amount, LedgerEntry.DISBURSEMENT),
        ]
        if terms.origination_fee_amount > 0:
            fee_revenue = self.account_repository.get_internal(Account.ORIGINATION_FEE_REVENUE)
            legs.append(LedgerLeg(account, -terms.origination_fee_amount, LedgerEntry.ORIGINATION_FEE))
            legs.append(LedgerLeg(fee_revenue, terms.origination_fee_amount, LedgerEntry.ORIGINATION_FEE))
        self.ledger_repository.post(legs, LedgerEntry.REF_LOAN, loan.id)

        self.outbox_repository.add(
            OutboxEvent.LOAN_CONTRACTED,
            "loan",
            loan,
            {
                "account_id": str(account.key),
                "customer_id": str(borrower.key),
                "principal_amount": amount,
                "net_amount": terms.net_amount,
                "installment_count": terms.installment_count,
            },
        )
        self.session.commit()

        return LoanDTO.loan_to_dict(loan), True

    # ── consulta ─────────────────────────────────────────────────────

    def get_by_id(self, raw_loan_id: str) -> dict:
        return LoanDTO.loan_to_dict(self._get_loan_or_raise(raw_loan_id))

    def list_by_account(self, raw_account_id: str, statuses: list, limit: int, cursor: Optional[str]) -> dict:
        account = self._get_account_or_raise(raw_account_id)

        try:
            after = decode_cursor(cursor)
            if after is not None:
                int(after[1])
        except (ValueError, TypeError, UnicodeDecodeError):
            raise InvalidParameter("cursor is not valid")

        loans = self.loan_repository.list_by_account(account.id, statuses, limit, after)

        next_cursor = None
        if len(loans) > limit:
            loans = loans[:limit]
            last = loans[-1]
            next_cursor = encode_cursor(last.contracted_at, last.id)

        return {
            "items": [LoanDTO.loan_to_dict(loan, with_installments=False) for loan in loans],
            "next_cursor": next_cursor,
        }

    # ── pagamento avulso ou antecipado ───────────────────────────────

    @retry_on_deadlock()
    def pay(self, raw_loan_id: str, payload: dict, idempotency_key: str) -> Tuple[dict, bool]:
        """Pagamento manual. As vencidas primeiro, da mais antiga à mais nova,
        pelo valor cheio; o que sobrar antecipa as futuras a valor presente.

          • REDUCE_TERM: antecipa da ÚLTIMA para a primeira — o prazo encurta.
          • REDUCE_INSTALLMENT: espalha pelas futuras na mesma proporção — cada
            parcela fica menor e o prazo não muda.

        Só o principal amortizado volta ao limite da linha do patrimônio.
        """
        if not is_valid_idempotency_key(idempotency_key):
            raise IdempotencyKeyRequired()

        payload_hash = request_hash(payload)
        replay = self._find_payment_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        unlocked_loan = self._get_loan_or_raise(raw_loan_id)

        locked = self.account_repository.lock_customer_accounts([unlocked_loan.account_id])
        account = locked.get(unlocked_loan.account_id)
        line = self.credit_line_repository.lock(unlocked_loan.credit_line_id)
        loan = self.loan_repository.lock(unlocked_loan.id)
        installments = self.loan_repository.lock_unpaid_installments(loan.id)

        replay = self._find_payment_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        if loan.status.enumerator == LoanStatus.PAID_OFF:
            raise LoanAlreadyPaidOff()

        if account is None or account.status.enumerator != AccountStatus.ACTIVE:
            status = account.status.enumerator if account is not None else None
            raise AccountNotActive(account.key if account is not None else None, status)

        amount = payload["amount"]
        today = self.calendar_repository.local_now().date()

        payoff = self._payoff_amount(loan, installments, today)
        if amount > payoff:
            raise AmountAboveDue(amount, payoff)

        if amount > account.available_balance:
            raise InsufficientBalance(amount, account.available_balance)

        allocations = self._allocate(loan, installments, amount, today, payload["mode"])

        try:
            payment = self.loan_repository.add_payment(
                loan, LoanPayment.MANUAL, amount, payload["mode"], idempotency_key, payload_hash
            )
        except IntegrityError:
            self.session.rollback()
            replay = self._find_payment_replay(idempotency_key, payload_hash)
            if replay is not None:
                return replay, False
            raise

        self._apply(account, line, loan, payment, allocations, f"payment {payment.key}")
        self.session.commit()

        return LoanDTO.payment_to_dict(payment, loan), True

    # ── cobrança automática (job collect_installments) ───────────────

    @retry_on_deadlock()
    def collect(self, loan_id: int, today: date) -> str:
        """Debita as parcelas vencidas até `today`, da mais antiga à mais nova.

        Debita o que houver de saldo disponível. O que não couber deixa a
        parcela OVERDUE (com os dias de atraso) e avisa a IF; o job tenta de
        novo no dia seguinte. Idempotente: parcela paga não é cobrada de novo.

        Devolve COLLECTED, PARTIAL, OVERDUE ou NOTHING_DUE.
        """
        loan = self.session.get(Loan, loan_id)
        if loan is None:
            return "NOTHING_DUE"

        locked = self.account_repository.lock_customer_accounts([loan.account_id])
        account = locked.get(loan.account_id)
        line = self.credit_line_repository.lock(loan.credit_line_id)
        loan = self.loan_repository.lock(loan.id)
        installments = [
            item for item in self.loan_repository.lock_unpaid_installments(loan.id) if item.due_date <= today
        ]

        if loan.status.enumerator != LoanStatus.ACTIVE or not installments:
            self.session.rollback()
            return "NOTHING_DUE"

        # Conta bloqueada também paga a própria dívida; encerrada ou recusada, não.
        can_debit = account is not None and account.status.enumerator in (AccountStatus.ACTIVE, AccountStatus.BLOCKED)
        available = max(account.available_balance, 0) if can_debit else 0

        allocations = []
        for installment in installments:
            if available <= 0:
                break
            value = min(installment.remaining_amount, available)
            allocations.append(self._split(installment, value, 0))
            available -= value

        result = "OVERDUE"
        if allocations:
            cash = sum(item.cash for item in allocations)
            payment = self.loan_repository.add_payment(loan, LoanPayment.AUTO_COLLECTION, cash, None)
            self._apply(account, line, loan, payment, allocations, "auto collection")
            result = "COLLECTED"

        overdue = []
        for installment in installments:
            if installment.remaining_amount > 0:
                installment.days_overdue = (today - installment.due_date).days
                self.loan_repository.update_installment_status(installment, InstallmentStatus.OVERDUE, "no balance")
                overdue.append(installment)

        if overdue:
            result = "PARTIAL" if allocations else "OVERDUE"
            for installment in overdue:
                self.outbox_repository.add(
                    OutboxEvent.INSTALLMENT_OVERDUE,
                    "installment",
                    installment,
                    {
                        "loan_id": str(loan.key),
                        "number": installment.number,
                        "due_date": installment.due_date.isoformat(),
                        "remaining_amount": installment.remaining_amount,
                        "days_overdue": installment.days_overdue,
                    },
                )

        self.session.commit()
        return result

    # ── peças ────────────────────────────────────────────────────────

    def _terms(self, line, payload: dict):
        installment_count = payload["installment_count"]
        term_days = 30 * installment_count
        if not MPO_MIN_TERM_DAYS <= term_days <= MPO_MAX_TERM_DAYS:
            raise OutOfMpoRule("installment_count", f"term must be {MPO_MIN_TERM_DAYS} to {MPO_MAX_TERM_DAYS} days")

        today = self.calendar_repository.local_now().date()
        return loan_terms(
            payload["amount"],
            installment_count,
            line.monthly_interest_rate,
            line.origination_fee_rate,
            today,
            self.calendar_repository.next_business_day_on_or_after,
        )

    def _split(self, installment: Installment, credited: int, discount: int) -> Allocation:
        """Divide o valor creditado na parcela: juros primeiro, depois principal.

        O desconto sai dos juros (é juro que deixou de existir).
        """
        interest_paid = min(installment.paid_amount, installment.interest_amount)
        interest_open = installment.interest_amount - interest_paid
        interest_part = min(credited, interest_open)
        principal_part = credited - interest_part
        discount = min(discount, interest_part)
        return Allocation(installment, principal_part, interest_part - discount, discount)

    def _future_discount(self, loan: Loan, installment: Installment, today: date) -> int:
        interest_open = installment.interest_amount - min(installment.paid_amount, installment.interest_amount)
        days_ahead = (installment.due_date - today).days
        return prepayment_discount(installment.remaining_amount, interest_open, loan.monthly_interest_rate, days_ahead)

    def _payoff_amount(self, loan: Loan, installments: List[Installment], today: date) -> int:
        """Quanto quita o contrato hoje: vencidas cheias + futuras a valor presente."""
        total = 0
        for installment in installments:
            if installment.due_date <= today:
                total += installment.remaining_amount
            else:
                total += installment.remaining_amount - self._future_discount(loan, installment, today)
        return total

    def _allocate(self, loan: Loan, installments: List[Installment], amount: int, today: date, mode: str):
        allocations = []
        left = amount

        due = [item for item in installments if item.due_date <= today]
        future = [item for item in installments if item.due_date > today]

        for installment in due:
            if left <= 0:
                break
            value = min(installment.remaining_amount, left)
            allocations.append(self._split(installment, value, 0))
            left -= value

        if left <= 0 or not future:
            return allocations

        priced = [(item, self._future_discount(loan, item, today)) for item in future]

        if mode == LoanPayment.REDUCE_TERM:
            # Da última para a primeira: as últimas somem e o prazo encurta.
            for installment, discount in reversed(priced):
                if left <= 0:
                    break
                cost = installment.remaining_amount - discount
                allocation = self._prepay(installment, min(left, cost), discount)
                allocations.append(allocation)
                left -= allocation.cash
            return allocations

        # REDUCE_INSTALLMENT: a mesma fração de cada parcela futura; os
        # centavos que o arredondamento deixar vão para as mais antigas.
        costs = [installment.remaining_amount - discount for installment, discount in priced]
        fraction = Decimal(left) / Decimal(sum(costs))
        targets = [int(Decimal(cost) * fraction) for cost in costs]
        leftover = left - sum(targets)
        for index, cost in enumerate(costs):
            extra = min(leftover, cost - targets[index])
            targets[index] += extra
            leftover -= extra

        for (installment, discount), cash in zip(priced, targets):
            if cash > 0:
                allocations.append(self._prepay(installment, cash, discount))
        return allocations

    def _prepay(self, installment: Installment, cash: int, discount: int) -> Allocation:
        """Antecipa uma parcela futura pagando `cash` em dinheiro.

        Inteira: credita o valor da parcela e perdoa o desconto cheio.
        Parcial: credita na proporção do valor presente (cash × valor ÷ custo),
        e o desconto é a diferença — sempre dentro dos juros em aberto, então
        o dinheiro alocado é exatamente `cash`.
        """
        remaining = installment.remaining_amount
        cost = remaining - discount
        if cost <= 0 or cash >= cost:
            return self._split(installment, remaining, discount)
        credited = cash * remaining // cost
        return self._split(installment, credited, credited - cash)

    def _apply(self, account: Account, line, loan: Loan, payment: LoanPayment, allocations, reason: str) -> None:
        """Grava o efeito do pagamento: parcelas, contrato, linha e ledger."""
        principal = 0
        interest = 0

        for allocation in allocations:
            installment = allocation.installment
            installment.paid_amount = installment.paid_amount + allocation.credited
            if installment.remaining_amount == 0:
                self.loan_repository.update_installment_status(installment, InstallmentStatus.PAID, reason)
            elif installment.due_date > self.calendar_repository.local_now().date():
                self.loan_repository.update_installment_status(installment, InstallmentStatus.PARTIAL, reason)
            self.loan_repository.add_allocation(
                payment, installment, allocation.principal, allocation.interest, allocation.discount
            )
            principal += allocation.principal
            interest += allocation.interest

        loan.outstanding_principal = max(loan.outstanding_principal - principal, 0)
        # Só o principal volta ao limite — e à linha do PATRIMÔNIO.
        line.available_limit = min(line.available_limit + principal, line.total_limit)

        cash = principal + interest
        if cash > 0:
            legs = [LedgerLeg(account, -cash, LedgerEntry.INSTALLMENT_PAYMENT)]
            if principal > 0:
                portfolio = self.account_repository.get_internal(Account.LOAN_PORTFOLIO)
                legs.append(LedgerLeg(portfolio, principal, LedgerEntry.INSTALLMENT_PAYMENT))
            if interest > 0:
                interest_revenue = self.account_repository.get_internal(Account.INTEREST_REVENUE)
                legs.append(LedgerLeg(interest_revenue, interest, LedgerEntry.INSTALLMENT_PAYMENT))
            self.ledger_repository.post(legs, LedgerEntry.REF_LOAN_PAYMENT, payment.id)

        self.session.flush()

        paid_off = all(item.status.enumerator == InstallmentStatus.PAID for item in loan.installments)
        if paid_off:
            loan.outstanding_principal = 0
            self.loan_repository.update_status(loan, LoanStatus.PAID_OFF, reason)
            self.outbox_repository.add(OutboxEvent.LOAN_PAID_OFF, "loan", loan, {"account_id": str(account.key)})

        self.outbox_repository.add(
            OutboxEvent.LOAN_PAYMENT,
            "loan",
            loan,
            {
                "payment_id": str(payment.key),
                "source": payment.source,
                "amount": cash,
                "principal_amount": principal,
                "interest_amount": interest,
                "outstanding_principal": loan.outstanding_principal,
            },
        )

    def _find_replay(self, idempotency_key: str, payload_hash: str) -> Optional[dict]:
        existing = self.loan_repository.get_by_idempotency_key(idempotency_key)
        if existing is None:
            return None
        if existing.request_hash != payload_hash:
            raise IdempotencyConflict(idempotency_key)
        return LoanDTO.loan_to_dict(existing)

    def _find_payment_replay(self, idempotency_key: str, payload_hash: str) -> Optional[dict]:
        existing = self.loan_repository.get_payment_by_idempotency_key(idempotency_key)
        if existing is None:
            return None
        if existing.request_hash != payload_hash:
            raise IdempotencyConflict(idempotency_key)
        return LoanDTO.payment_to_dict(existing, existing.loan)

    def _get_account_or_raise(self, raw_account_id: str) -> Account:
        account_key = parse_uuid(raw_account_id)
        account = self.account_repository.get_customer_account(account_key) if account_key is not None else None
        if account is None:
            raise AccountNotFound(raw_account_id)
        return account

    def _get_loan_or_raise(self, raw_loan_id: str) -> Loan:
        loan_key = parse_uuid(raw_loan_id)
        loan = self.loan_repository.get_by_key(loan_key) if loan_key is not None else None
        if loan is None:
            raise LoanNotFound(raw_loan_id)
        return loan
