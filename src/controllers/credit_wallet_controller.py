from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import CardDTO
from errors import (
    AccountNotActive,
    AccountNotFound,
    CreditWalletAlreadyExists,
    CreditWalletNotFound,
    InvalidResourceStatusTransition,
    InvoiceNotFound,
    LimitBelowUsed,
)
from models import AccountStatus, CreditWallet, CreditWalletStatus, OutboxEvent
from repositories import AccountRepository, CreditWalletRepository, InvoiceRepository, OutboxRepository
from utils.db_retry import retry_on_deadlock
from utils.ids import parse_uuid

# Quais estados existem é a tabela credit_wallet_status; quais transições
# valem é este dicionário. CLOSED é final.
ALLOWED_TRANSITIONS = {
    CreditWalletStatus.ACTIVE: {CreditWalletStatus.BLOCKED, CreditWalletStatus.CLOSED},
    CreditWalletStatus.BLOCKED: {CreditWalletStatus.ACTIVE, CreditWalletStatus.CLOSED},
}


class CreditWalletController(BaseController):
    """Carteira de crédito (QI: wallet). O limite é informado pela IF:
    este time não calcula risco, só aplica o número que recebe."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.wallet_repository = CreditWalletRepository(self.context)
        self.account_repository = AccountRepository(self.context)
        self.invoice_repository = InvoiceRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)

    @retry_on_deadlock()
    def create(self, raw_account_id: str, payload: dict) -> dict:
        account_id = parse_uuid(raw_account_id)
        locked = self.account_repository.lock_customer_accounts([account_id]) if account_id is not None else {}
        account = locked.get(account_id)
        if account is None:
            raise AccountNotFound(raw_account_id)

        if account.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(account.id, account.status.enumerator)

        if self.wallet_repository.get_live_by_account(account.id) is not None:
            raise CreditWalletAlreadyExists(account.id)

        try:
            wallet = self.wallet_repository.create(account.id, payload)
        except IntegrityError:
            # O índice parcial ux_credit_wallet_live é a última palavra.
            self.session.rollback()
            raise CreditWalletAlreadyExists(account.id)

        self._outbox(wallet, None)
        self.session.commit()

        return CardDTO.wallet_to_dict(wallet)

    def get_by_id(self, raw_wallet_id: str) -> dict:
        return CardDTO.wallet_to_dict(self._get_or_raise(raw_wallet_id))

    @retry_on_deadlock()
    def update_limit(self, raw_wallet_id: str, total_limit: int) -> dict:
        """Novo limite nunca abaixo do já usado (QI CIN000110)."""
        wallet = self._lock_or_raise(raw_wallet_id)

        if total_limit < wallet.used_limit:
            raise LimitBelowUsed(total_limit, wallet.used_limit)

        wallet.total_limit = total_limit
        self.session.commit()

        return CardDTO.wallet_to_dict(wallet)

    @retry_on_deadlock()
    def update_status(self, raw_wallet_id: str, new_status: str, reason: str) -> dict:
        wallet = self._lock_or_raise(raw_wallet_id)
        old_status = wallet.status.enumerator

        if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
            raise InvalidResourceStatusTransition("Credit wallet", old_status, new_status)

        if new_status == CreditWalletStatus.CLOSED and wallet.used_limit != 0:
            raise InvalidResourceStatusTransition("Credit wallet with used limit", old_status, new_status)

        self.wallet_repository.update_status(wallet, new_status, reason)
        self._outbox(wallet, old_status)
        self.session.commit()

        return CardDTO.wallet_to_dict(wallet)

    def list_invoices(self, raw_wallet_id: str, statuses: list) -> dict:
        wallet = self._get_or_raise(raw_wallet_id)
        invoices = self.invoice_repository.list_by_wallet(wallet.id, statuses)
        return {"items": [CardDTO.invoice_to_dict(invoice) for invoice in invoices]}

    def get_invoice(self, raw_invoice_id: str) -> dict:
        invoice_id = parse_uuid(raw_invoice_id)
        invoice = self.invoice_repository.get_by_id(invoice_id) if invoice_id is not None else None
        if invoice is None:
            raise InvoiceNotFound(raw_invoice_id)
        return CardDTO.invoice_to_dict(invoice, with_items=True)

    def _get_or_raise(self, raw_wallet_id: str) -> CreditWallet:
        wallet_id = parse_uuid(raw_wallet_id)
        wallet = self.wallet_repository.get_by_id(wallet_id) if wallet_id is not None else None
        if wallet is None:
            raise CreditWalletNotFound(raw_wallet_id)
        return wallet

    def _lock_or_raise(self, raw_wallet_id: str) -> CreditWallet:
        """Ordem global: a conta dona primeiro, a carteira depois."""
        wallet = self._get_or_raise(raw_wallet_id)
        self.account_repository.lock_customer_accounts([wallet.account_id])
        return self.wallet_repository.lock(wallet.id)

    def _outbox(self, wallet: CreditWallet, old_status) -> None:
        self.outbox_repository.add(
            OutboxEvent.CREDIT_WALLET_STATUS_CHANGED,
            "credit_wallet",
            wallet.id,
            {"status": wallet.status.enumerator, "old_status": old_status},
        )