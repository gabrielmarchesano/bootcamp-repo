from typing import Optional
from uuid import UUID

from sqlalchemy import func

from database import Context
from models import CreditWallet, CreditWalletStatus, CreditWalletStatusEvent
from repositories.enumerator_repository import EnumeratorRepository
from repositories.status_event_recorder import record_status_event


class CreditWalletRepository:
    """Carteira de crédito. Na ordem global de lock, vem logo depois da conta:
    account → credit_wallet → card → card_authorization → invoice."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

    def create(self, account_id: UUID, data: dict) -> CreditWallet:
        wallet = CreditWallet()
        wallet.account_id = account_id
        wallet.total_limit = data["total_limit"]
        wallet.used_limit = 0
        wallet.closing_day = data["closing_day"]
        wallet.due_day = data["due_day"]
        wallet.monthly_interest_rate = data["monthly_interest_rate"]
        wallet.fine_rate = data["fine_rate"]
        wallet.autopay = data.get("autopay", False)
        wallet.status = self.enumerators.get(CreditWalletStatus, CreditWalletStatus.ACTIVE)

        self.session.add(wallet)
        record_status_event(self.session, CreditWalletStatusEvent, "credit_wallet", wallet, None, wallet.status, None)
        self.session.flush()
        return wallet

    def get_by_id(self, wallet_id: UUID) -> Optional[CreditWallet]:
        return self.session.query(CreditWallet).filter(CreditWallet.id == wallet_id).first()

    def get_live_by_account(self, account_id: UUID) -> Optional[CreditWallet]:
        """A carteira ACTIVE ou BLOCKED da conta (o índice parcial garante no máximo uma)."""
        return (
            self.session.query(CreditWallet)
            .join(CreditWallet.status)
            .filter(
                CreditWallet.account_id == account_id,
                CreditWalletStatus.enumerator.in_((CreditWalletStatus.ACTIVE, CreditWalletStatus.BLOCKED)),
            )
            .first()
        )

    def lock(self, wallet_id: UUID) -> Optional[CreditWallet]:
        return (
            self.session.query(CreditWallet)
            .filter(CreditWallet.id == wallet_id)
            .populate_existing()
            .with_for_update()
            .first()
        )

    def update_status(self, wallet: CreditWallet, new_status: str, reason: Optional[str]) -> None:
        old_status = wallet.status
        wallet.status = self.enumerators.get(CreditWalletStatus, new_status)
        wallet.updated_at = func.now()
        record_status_event(self.session, CreditWalletStatusEvent, "credit_wallet", wallet, old_status, wallet.status, reason)

    def change_used_limit(self, wallet: CreditWallet, delta: int) -> None:
        """Soma (ou subtrai) do limite usado, sem deixar negativo."""
        wallet.used_limit = max(wallet.used_limit + delta, 0)
        wallet.updated_at = func.now()