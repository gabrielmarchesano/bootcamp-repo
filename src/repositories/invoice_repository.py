from datetime import date
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func

from database import Context
from models import CreditWallet, Invoice, InvoiceItem, InvoiceStatus, InvoiceStatusEvent
from repositories.enumerator_repository import EnumeratorRepository
from repositories.status_event_recorder import record_status_event


class InvoiceRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

    def get_by_id(self, invoice_id: UUID) -> Optional[Invoice]:
        return self.session.query(Invoice).filter(Invoice.id == invoice_id).first()

    def list_by_wallet(self, wallet_id: UUID, statuses: List[str]) -> List[Invoice]:
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
        authorization_id: UUID,
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