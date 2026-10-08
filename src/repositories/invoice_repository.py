from datetime import date
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, text

from database import Context
from models import CreditWallet, Invoice, InvoiceItem, InvoicePayment, InvoiceStatus, InvoiceStatusEvent
from repositories.enumerator_repository import EnumeratorRepository
from repositories.status_event_recorder import record_status_event


class InvoiceRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

    def get_by_key(self, invoice_key: UUID) -> Optional[Invoice]:
        return self.session.query(Invoice).filter(Invoice.key == invoice_key).first()

    def lock(self, invoice_id: int) -> Optional[Invoice]:
        """Trava a fatura. Só depois da conta e da carteira (ordem global)."""
        return (
            self.session.query(Invoice)
            .filter(Invoice.id == invoice_id)
            .populate_existing()
            .with_for_update()
            .first()
        )

    def get_open(self, wallet_id: int) -> Optional[Invoice]:
        return (
            self.session.query(Invoice)
            .join(Invoice.status)
            .filter(Invoice.wallet_id == wallet_id, InvoiceStatus.enumerator == InvoiceStatus.OPEN)
            .first()
        )

    def get_next_future(self, wallet_id: int) -> Optional[Invoice]:
        return (
            self.session.query(Invoice)
            .join(Invoice.status)
            .filter(Invoice.wallet_id == wallet_id, InvoiceStatus.enumerator == InvoiceStatus.FUTURE)
            .order_by(Invoice.reference_month)
            .first()
        )

    def list_by_status(self, statuses, date_column=None, until=None) -> List[Invoice]:
        """Faturas nos status pedidos; com `date_column`/`until`, só as com a data até `until`."""
        query = self.session.query(Invoice).join(Invoice.status).filter(InvoiceStatus.enumerator.in_(statuses))
        if date_column is not None:
            query = query.filter(getattr(Invoice, date_column) <= until)
        return query.order_by(Invoice.id).all()

    def update_status(self, invoice: Invoice, new_status: str, reason: Optional[str] = None) -> None:
        old_status = invoice.status
        if old_status is not None and old_status.enumerator == new_status:
            return
        invoice.status = self.enumerators.get(InvoiceStatus, new_status)
        invoice.updated_at = func.now()
        record_status_event(self.session, InvoiceStatusEvent, "invoice", invoice, old_status, invoice.status, reason)

    def outstanding(self, invoice: Invoice) -> int:
        return max(invoice.total_amount - invoice.paid_amount, 0)

    def charges_total(self, invoice: Invoice) -> int:
        """Encargos (rotativo/parcelamento) já lançados nesta fatura."""
        return self.session.execute(
            text(
                "SELECT COALESCE(SUM(amount), 0) FROM invoice_item "
                "WHERE invoice_id = :invoice_id AND type = 'REVOLVING_CHARGE'"
            ),
            {"invoice_id": invoice.id},
        ).scalar_one()

    def add_payment(self, invoice: Invoice, source: str, amount: int, idempotency_key=None, request_hash=None):
        payment = InvoicePayment()
        payment.invoice_id = invoice.id
        payment.source = source
        payment.amount = amount
        payment.idempotency_key = idempotency_key
        payment.request_hash = request_hash
        invoice.paid_amount = invoice.paid_amount + amount
        invoice.updated_at = func.now()
        self.session.add(payment)
        self.session.flush()
        return payment

    def get_payment_by_idempotency_key(self, idempotency_key: str) -> Optional[InvoicePayment]:
        return (
            self.session.query(InvoicePayment).filter(InvoicePayment.idempotency_key == idempotency_key).first()
        )

    def has_autopay(self, invoice: Invoice) -> bool:
        return (
            self.session.query(InvoicePayment)
            .filter(InvoicePayment.invoice_id == invoice.id, InvoicePayment.source == InvoicePayment.AUTOPAY)
            .first()
            is not None
        )

    def list_by_wallet(self, wallet_id: int, statuses: List[str]) -> List[Invoice]:
        """Faturas da carteira, mais nova primeiro. Sem paginação: é uma por mês."""
        query = self.session.query(Invoice).filter(Invoice.wallet_id == wallet_id)
        if statuses:
            query = query.join(Invoice.status).filter(InvoiceStatus.enumerator.in_(statuses))
        return query.order_by(Invoice.reference_month.desc()).all()

    def get_or_create(self, wallet: CreditWallet, reference_month: date, closing_date: date, due_date: date) -> Invoice:
        """A fatura do mês, criada na primeira vez que alguém precisa dela.

        Nasce OPEN se a carteira não tem fatura aberta; senão nasce FUTURE e
        vira OPEN quando a aberta fechar (job close_invoices). Quem chama já
        travou a carteira, então duas capturas não criam a mesma fatura.
        """
        invoice = (
            self.session.query(Invoice)
            .filter(Invoice.wallet_id == wallet.id, Invoice.reference_month == reference_month)
            .first()
        )
        if invoice is not None:
            return invoice

        open_invoice = (
            self.session.query(Invoice)
            .join(Invoice.status)
            .filter(Invoice.wallet_id == wallet.id, InvoiceStatus.enumerator == InvoiceStatus.OPEN)
            .first()
        )
        status = InvoiceStatus.FUTURE if open_invoice is not None else InvoiceStatus.OPEN

        invoice = Invoice()
        invoice.wallet_id = wallet.id
        invoice.reference_month = reference_month
        invoice.closing_date = closing_date
        invoice.due_date = due_date
        invoice.total_amount = 0
        invoice.paid_amount = 0
        invoice.status = self.enumerators.get(InvoiceStatus, status)

        self.session.add(invoice)
        record_status_event(self.session, InvoiceStatusEvent, "invoice", invoice, None, invoice.status, None)
        self.session.flush()
        return invoice

    def add_item(
        self,
        invoice: Invoice,
        authorization_id: Optional[int],
        item_type: str,
        amount: int,
        installment_number: int,
        installment_total: int,
        description: Optional[str],
    ) -> InvoiceItem:
        item = InvoiceItem()
        item.invoice_id = invoice.id
        item.card_authorization_id = authorization_id
        item.type = item_type
        item.amount = amount
        item.installment_number = installment_number
        item.installment_total = installment_total
        item.description = description

        invoice.total_amount = invoice.total_amount + amount
        invoice.updated_at = func.now()

        self.session.add(item)
        return item