from datetime import date
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import CardDTO
from errors import (
    AccountNotActive,
    AmountAboveInvoice,
    IdempotencyConflict,
    IdempotencyKeyRequired,
    InsufficientBalance,
    InvoiceAlreadyPaid,
    InvoiceNotChargeable,
    InvoiceNotFound,
    RevolvingCapExceeded,
)
from models import Account, AccountStatus, Invoice, InvoiceItem, InvoicePayment, InvoiceStatus, LedgerEntry, OutboxEvent
from repositories import (
    AccountRepository,
    CalendarRepository,
    CreditWalletRepository,
    InvoiceRepository,
    LedgerLeg,
    LedgerRepository,
    OutboxRepository,
)
from utils.db_retry import retry_on_deadlock
from utils.idempotency import is_valid_idempotency_key, request_hash
from utils.ids import parse_uuid

# Fatura ainda não fechada: o pagamento é antecipação, o status não muda.
NOT_CLOSED = (InvoiceStatus.OPEN, InvoiceStatus.FUTURE)


class InvoiceController(BaseController):
    """Pagamento, encargo, fechamento e atraso da fatura.

    Ordem de lock: conta → carteira → fatura (a global dos cartões).
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.invoice_repository = InvoiceRepository(self.context)
        self.wallet_repository = CreditWalletRepository(self.context)
        self.account_repository = AccountRepository(self.context)
        self.ledger_repository = LedgerRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)
        self.calendar_repository = CalendarRepository(self.context)

    # ── pagamento manual ─────────────────────────────────────────────

    @retry_on_deadlock()
    def pay(self, raw_invoice_id: str, payload: dict, idempotency_key: str) -> Tuple[dict, bool]:
        """Paga a fatura, total ou parcial: debita a conta e devolve o limite da carteira."""
        if not is_valid_idempotency_key(idempotency_key):
            raise IdempotencyKeyRequired()

        payload_hash = request_hash(payload)
        replay = self._find_payment_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        account, wallet, invoice = self._lock(raw_invoice_id)

        replay = self._find_payment_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        if invoice.status.enumerator == InvoiceStatus.PAID:
            raise InvoiceAlreadyPaid()

        if account.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(account.key, account.status.enumerator)

        amount = payload["amount"]
        outstanding = self.invoice_repository.outstanding(invoice)
        if amount > outstanding:
            raise AmountAboveInvoice(amount, outstanding)

        if amount > account.available_balance:
            raise InsufficientBalance(amount, account.available_balance)

        try:
            payment = self.invoice_repository.add_payment(
                invoice, InvoicePayment.MANUAL, amount, idempotency_key, payload_hash
            )
        except IntegrityError:
            self.session.rollback()
            replay = self._find_payment_replay(idempotency_key, payload_hash)
            if replay is not None:
                return replay, False
            raise

        self._settle(account, wallet, invoice, payment)
        self.session.commit()

        return self._payment_body(payment, invoice), True

    # ── encargo do rotativo / parcelamento ───────────────────────────

    @retry_on_deadlock()
    def charge(self, raw_invoice_id: str, payload: dict, idempotency_key: str) -> Tuple[dict, bool]:
        """A IF lança o encargo na fatura vencida, dentro do teto do rotativo.

        Lei 14.690/2023: juros e encargos acumulados não passam de 100% da
        dívida original (`original_debt_amount`, gravada quando a fatura
        venceu). O encargo vira item REVOLVING_CHARGE na própria fatura em
        atraso — é lá que a dívida mora — e consome limite da carteira.
        """
        if not is_valid_idempotency_key(idempotency_key):
            raise IdempotencyKeyRequired()

        payload_hash = request_hash(payload)
        replay = self._find_charge_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        account, wallet, invoice = self._lock(raw_invoice_id)

        replay = self._find_charge_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        if invoice.status.enumerator != InvoiceStatus.OVERDUE or invoice.original_debt_amount is None:
            raise InvoiceNotChargeable(invoice.status.enumerator)

        amount = payload["amount"]
        total_charges = self.invoice_repository.charges_total(invoice) + amount
        if total_charges > invoice.original_debt_amount:
            raise RevolvingCapExceeded(total_charges, invoice.original_debt_amount)

        try:
            item = self.invoice_repository.add_item(
                invoice,
                None,
                InvoiceItem.REVOLVING_CHARGE,
                amount,
                1,
                1,
                f"Encargo {payload['type']}",
                idempotency_key,
                payload_hash,
            )
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            replay = self._find_charge_replay(idempotency_key, payload_hash)
            if replay is not None:
                return replay, False
            raise

        # Sem trava em used_limit <= total_limit: encargo pode passar do limite.
        self.wallet_repository.change_used_limit(wallet, amount)

        self.outbox_repository.add(
            OutboxEvent.INVOICE_CHARGE,
            "invoice",
            invoice,
            {"type": payload["type"], "amount": amount, "total_charges": total_charges},
        )
        self.session.commit()

        return self._charge_body(item, invoice), True

    # ── jobs ─────────────────────────────────────────────────────────

    @retry_on_deadlock()
    def close(self, invoice_id: int, today: date) -> str:
        """OPEN → CLOSED no dia do fechamento; a FUTURE seguinte vira OPEN.

        Fatura que fecha sem nada a pagar já nasce PAID. Idempotente: se a
        fatura já não está OPEN (ou ainda não chegou o dia), nada muda.
        """
        account, wallet, invoice = self._lock_by_id(invoice_id)

        if invoice.status.enumerator != InvoiceStatus.OPEN or invoice.closing_date > today:
            self.session.rollback()
            return "SKIPPED"

        new_status = InvoiceStatus.PAID if self.invoice_repository.outstanding(invoice) == 0 else InvoiceStatus.CLOSED
        self.invoice_repository.update_status(invoice, new_status, "closing day")
        # O índice ux_invoice_open aceita uma OPEN por carteira: a atual sai
        # do OPEN no banco antes de a próxima entrar.
        self.session.flush()

        next_invoice = self.invoice_repository.get_next_future(wallet.id)
        if next_invoice is not None:
            next_invoice = self.invoice_repository.lock(next_invoice.id)
            self.invoice_repository.update_status(next_invoice, InvoiceStatus.OPEN, "previous invoice closed")

        self._status_outbox(invoice)
        self.session.commit()
        return new_status

    @retry_on_deadlock()
    def mark_overdue(self, invoice_id: int, today: date) -> str:
        """CLOSED/PARTIALLY_PAID vencida e não quitada → OVERDUE, com a dívida original."""
        account, wallet, invoice = self._lock_by_id(invoice_id)

        if invoice.status.enumerator not in (InvoiceStatus.CLOSED, InvoiceStatus.PARTIALLY_PAID):
            self.session.rollback()
            return "SKIPPED"

        outstanding = self.invoice_repository.outstanding(invoice)
        if invoice.due_date >= today or outstanding == 0:
            self.session.rollback()
            return "SKIPPED"

        invoice.original_debt_amount = outstanding
        self.invoice_repository.update_status(invoice, InvoiceStatus.OVERDUE, "past due date")
        self._status_outbox(invoice)
        self.session.commit()
        return InvoiceStatus.OVERDUE

    @retry_on_deadlock()
    def autopay(self, invoice_id: int, today: date) -> str:
        """Débito automático no vencimento: no máximo um por fatura (ux_invoice_payment_autopay).

        Debita o que houver de saldo, até o valor da fatura. Sem saldo, não
        cria pagamento — a fatura segue para o fluxo de atraso.
        """
        account, wallet, invoice = self._lock_by_id(invoice_id)

        payable = (InvoiceStatus.CLOSED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.OVERDUE)
        if (
            not wallet.autopay
            or invoice.status.enumerator not in payable
            or invoice.due_date > today
            or self.invoice_repository.has_autopay(invoice)
        ):
            self.session.rollback()
            return "SKIPPED"

        if account.status.enumerator not in (AccountStatus.ACTIVE, AccountStatus.BLOCKED):
            self.session.rollback()
            return "SKIPPED"

        amount = min(self.invoice_repository.outstanding(invoice), max(account.available_balance, 0))
        if amount <= 0:
            self.session.rollback()
            return "NO_BALANCE"

        payment = self.invoice_repository.add_payment(invoice, InvoicePayment.AUTOPAY, amount)
        self._settle(account, wallet, invoice, payment)
        self.session.commit()
        return invoice.status.enumerator

    # ── peças ────────────────────────────────────────────────────────

    def _settle(self, account: Account, wallet, invoice: Invoice, payment: InvoicePayment) -> None:
        """Ledger, limite da carteira, status e evento de um pagamento já gravado."""
        settlement = self.account_repository.get_internal(Account.CARD_SETTLEMENT)
        legs = [
            LedgerLeg(account, -payment.amount, LedgerEntry.INVOICE_PAYMENT, "CARD"),
            LedgerLeg(settlement, payment.amount, LedgerEntry.INVOICE_PAYMENT, "CARD"),
        ]
        self.ledger_repository.post(legs, LedgerEntry.REF_INVOICE_PAYMENT, payment.id)

        self.wallet_repository.change_used_limit(wallet, -payment.amount)

        status = invoice.status.enumerator
        if status not in NOT_CLOSED:
            if self.invoice_repository.outstanding(invoice) == 0:
                self.invoice_repository.update_status(invoice, InvoiceStatus.PAID, f"payment {payment.key}")
            elif status == InvoiceStatus.CLOSED:
                self.invoice_repository.update_status(invoice, InvoiceStatus.PARTIALLY_PAID, f"payment {payment.key}")

        self.outbox_repository.add(
            OutboxEvent.INVOICE_PAYMENT,
            "invoice",
            invoice,
            {
                "payment_id": str(payment.key),
                "source": payment.source,
                "amount": payment.amount,
                "status": invoice.status.enumerator,
                "remaining_amount": self.invoice_repository.outstanding(invoice),
            },
        )

    def _status_outbox(self, invoice: Invoice) -> None:
        self.outbox_repository.add(
            OutboxEvent.INVOICE_STATUS_CHANGED,
            "invoice",
            invoice,
            {
                "status": invoice.status.enumerator,
                "total_amount": invoice.total_amount,
                "due_date": invoice.due_date.isoformat(),
                "original_debt_amount": invoice.original_debt_amount,
            },
        )

    def _lock(self, raw_invoice_id: str):
        invoice_key = parse_uuid(raw_invoice_id)
        invoice = self.invoice_repository.get_by_key(invoice_key) if invoice_key is not None else None
        if invoice is None:
            raise InvoiceNotFound(raw_invoice_id)
        return self._lock_by_id(invoice.id)

    def _lock_by_id(self, invoice_id: int):
        """Conta → carteira → fatura, a ordem global."""
        invoice = self.session.get(Invoice, invoice_id)
        wallet = invoice.wallet
        locked = self.account_repository.lock_customer_accounts([wallet.account_id])
        account = locked[wallet.account_id]
        wallet = self.wallet_repository.lock(wallet.id)
        invoice = self.invoice_repository.lock(invoice.id)
        return account, wallet, invoice

    def _payment_body(self, payment: InvoicePayment, invoice: Invoice) -> dict:
        return {
            "payment_id": str(payment.key),
            "invoice_id": str(invoice.key),
            "source": payment.source,
            "amount": payment.amount,
            "status": invoice.status.enumerator,
            "paid_amount": invoice.paid_amount,
            "remaining_amount": self.invoice_repository.outstanding(invoice),
            "created_at": payment.created_at.isoformat(),
        }

    def _charge_body(self, item: InvoiceItem, invoice: Invoice) -> dict:
        body = CardDTO.invoice_to_dict(invoice, with_items=True)
        body["charge"] = {"invoice_item_id": str(item.key), "amount": item.amount, "description": item.description}
        return body

    def _find_payment_replay(self, idempotency_key: str, payload_hash: str) -> Optional[dict]:
        existing = self.invoice_repository.get_payment_by_idempotency_key(idempotency_key)
        if existing is None:
            return None
        if existing.request_hash != payload_hash:
            raise IdempotencyConflict(idempotency_key)
        return self._payment_body(existing, existing.invoice)

    def _find_charge_replay(self, idempotency_key: str, payload_hash: str) -> Optional[dict]:
        existing = self.invoice_repository.get_charge_by_idempotency_key(idempotency_key)
        if existing is None:
            return None
        if existing.request_hash != payload_hash:
            raise IdempotencyConflict(idempotency_key)
        return self._charge_body(existing, existing.invoice)
