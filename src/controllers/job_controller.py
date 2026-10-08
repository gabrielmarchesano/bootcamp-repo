from datetime import timedelta
from typing import Callable, Dict

from controllers.base_controller import BaseController
from controllers.card_authorization_controller import CardAuthorizationController
from controllers.invoice_controller import InvoiceController
from controllers.loan_controller import LoanController
from controllers.transfer_controller import TransferController
from controllers.webhook_controller import WebhookController
from connectors.if_webhook_connector import IfWebhookConnector
from errors import NotFoundResource
from models import CreditWallet, Invoice, InvoiceStatus, Transfer
from repositories import (
    CalendarRepository,
    CardAuthorizationRepository,
    InvoiceRepository,
    LoanRepository,
    OutboxRepository,
    TransferRepository,
)
from utils.rail_mock import query_transfer_status

# Quanto tempo uma transferência fica SENT antes de a reconciliação perguntar ao trilho.
RECONCILE_AFTER = timedelta(minutes=30)

# Lote do despacho do outbox e quantas tentativas antes de FAILED.
OUTBOX_BATCH = 100
OUTBOX_MAX_ATTEMPTS = 5


class JobController(BaseController):
    """Os 8 jobs agendados. Todos idempotentes: rodar duas vezes no mesmo dia
    não move dinheiro de novo.

    Cada job lista os candidatos SEM lock e processa um por um, cada um na
    própria transação, pelo mesmo controller que a rota usaria — mesmas
    regras, mesma ordem de lock. Um item que falha não derruba o lote.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.calendar_repository = CalendarRepository(self.context)
        self.loan_repository = LoanRepository(self.context)
        self.invoice_repository = InvoiceRepository(self.context)
        self.transfer_repository = TransferRepository(self.context)
        self.authorization_repository = CardAuthorizationRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)

    def run(self, job_name: str) -> dict:
        jobs: Dict[str, Callable[[], dict]] = {
            "collect_installments": self.collect_installments,
            "run_scheduled_teds": self.run_scheduled_teds,
            "reconcile_spi_str": self.reconcile_spi_str,
            "expire_authorizations": self.expire_authorizations,
            "close_invoices": self.close_invoices,
            "run_invoice_autopay": self.run_invoice_autopay,
            "mark_overdue_invoices": self.mark_overdue_invoices,
            "dispatch_outbox_events": self.dispatch_outbox_events,
        }
        job = jobs.get(job_name)
        if job is None:
            raise NotFoundResource()

        self.logger.info(f"JOB {job_name} started")
        result = job()
        self.session.commit()
        self.logger.info(f"JOB {job_name} finished: {result}")
        return {"job": job_name, "result": result}

    # ── microcrédito ─────────────────────────────────────────────────

    def collect_installments(self) -> dict:
        today = self._today()
        candidates = self.loan_repository.list_due_loans(today)
        self.session.rollback()

        controller = LoanController()
        return self._each(candidates, lambda item: controller.collect(item[0], today))

    # ── transferências ───────────────────────────────────────────────

    def run_scheduled_teds(self) -> dict:
        """Só em dia útil e dentro da janela do STR; fora dela, as TEDs esperam."""
        controller = TransferController()
        if not controller.ted_window_open():
            return {"processed": 0, "skipped_reason": "STR window closed"}

        today = self._today()
        candidates = [transfer.id for transfer in self.transfer_repository.list_scheduled_due(today)]
        self.session.rollback()

        return self._each(candidates, controller.execute_scheduled_ted)

    def reconcile_spi_str(self) -> dict:
        """Pergunta ao trilho o desfecho do que ficou SENT; sem resposta, não mexe."""
        moment = self.calendar_repository.local_now() - RECONCILE_AFTER
        candidates = [
            (transfer.id, transfer.method, transfer.end_to_end_id or transfer.str_control_number)
            for transfer in self.transfer_repository.list_sent_before(moment)
        ]
        self.session.rollback()

        webhook = WebhookController()

        def reconcile(item) -> str:
            transfer_id, method, external_id = item
            rail = "SPI" if method == Transfer.PIX else "STR"
            answer = query_transfer_status(rail, external_id)
            if answer is None:
                return "NO_ANSWER"

            transfer = webhook.session.get(Transfer, transfer_id)
            status = answer.get("status")
            if status == "SETTLED":
                webhook.settle(transfer, method, external_id)
            elif status == "REJECTED" and method == Transfer.PIX:
                webhook.reject_pix(transfer, {"end_to_end_id": external_id, "error_code": answer.get("error_code")})
            elif status == "RETURNED" and method == Transfer.TED:
                webhook.return_ted(transfer, {"str_control_number": external_id, "reason": answer.get("reason")})
            return status

        return self._each(candidates, reconcile)

    # ── cartões e faturas ────────────────────────────────────────────

    def expire_authorizations(self) -> dict:
        candidates = self.authorization_repository.list_expired_authorization_ids()
        self.session.rollback()

        controller = CardAuthorizationController()
        return self._each(candidates, lambda item: "EXPIRED" if controller.expire(item) else "SKIPPED")

    def close_invoices(self) -> dict:
        today = self._today()
        candidates = [
            invoice.id
            for invoice in self.invoice_repository.list_by_status([InvoiceStatus.OPEN], "closing_date", today)
        ]
        self.session.rollback()

        controller = InvoiceController()
        return self._each(candidates, lambda item: controller.close(item, today))

    def mark_overdue_invoices(self) -> dict:
        today = self._today()
        statuses = [InvoiceStatus.CLOSED, InvoiceStatus.PARTIALLY_PAID]
        candidates = [
            invoice.id
            for invoice in self.invoice_repository.list_by_status(statuses, "due_date", today - timedelta(days=1))
        ]
        self.session.rollback()

        controller = InvoiceController()
        return self._each(candidates, lambda item: controller.mark_overdue(item, today))

    def run_invoice_autopay(self) -> dict:
        today = self._today()
        statuses = [InvoiceStatus.CLOSED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.OVERDUE]
        candidates = [
            invoice.id
            for invoice in self.session.query(Invoice)
            .join(Invoice.status)
            .join(CreditWallet, CreditWallet.id == Invoice.wallet_id)
            .filter(InvoiceStatus.enumerator.in_(statuses), Invoice.due_date <= today, CreditWallet.autopay.is_(True))
            .order_by(Invoice.id)
            .all()
        ]
        self.session.rollback()

        controller = InvoiceController()
        return self._each(candidates, lambda item: controller.autopay(item, today))

    # ── outbox ───────────────────────────────────────────────────────

    def dispatch_outbox_events(self) -> dict:
        """Entrega à IF os eventos PENDING, do mais antigo ao mais novo.

        A chamada HTTP acontece FORA de transação e sem linha travada; só a
        marcação (SENT ou mais uma tentativa) trava o evento, com SKIP LOCKED.
        Entrega pelo menos uma vez: a IF deduplica pelo `event_id`.
        """
        events = [
            (event.id, event.type, event.aggregate_type, str(event.aggregate_id), event.payload)
            for event in self.outbox_repository.list_pending(OUTBOX_BATCH)
        ]
        self.session.rollback()

        connector = IfWebhookConnector()

        def dispatch(item) -> str:
            event_id, event_type, aggregate_type, aggregate_key, payload = item
            delivered = connector.deliver(event_type, aggregate_type, aggregate_key, payload, event_id)

            event = self.outbox_repository.lock_pending(event_id)
            if event is None:
                self.session.rollback()
                return "SKIPPED"
            if delivered:
                self.outbox_repository.mark_sent(event)
            else:
                self.outbox_repository.mark_failed_attempt(event, OUTBOX_MAX_ATTEMPTS)
            self.session.commit()
            return "SENT" if delivered else "RETRY"

        return self._each(events, dispatch)

    # ── peças ────────────────────────────────────────────────────────

    def _today(self):
        return self.calendar_repository.local_now().date()

    def _each(self, candidates, process) -> dict:
        """Roda `process` em cada candidato; conta os desfechos e os erros."""
        outcomes: Dict[str, int] = {}
        for candidate in candidates:
            try:
                outcome = process(candidate)
            except Exception as error:  # noqa: BLE001 — um item ruim não derruba o lote
                self.session.rollback()
                self.logger.error(f"job item {candidate} failed: {error!r}")
                outcome = "ERROR"
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        return {"processed": len(candidates), "outcomes": outcomes}
