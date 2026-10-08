from controllers.base_controller import BaseController
from dtos import AccountDTO
from errors import AccountCannotBeClosed, AccountNotFound, InvalidParameter, InvalidStatusTransition
from models import Account, AccountStatus, OutboxEvent
from repositories import AccountRepository, LedgerRepository, OutboxRepository
from utils.cursor import decode_cursor, encode_cursor
from utils.db_retry import retry_on_deadlock
from utils.ids import parse_uuid

# ────────────────────────────────────────────────────────────────────
# QUEM PODE VIRAR O QUÊ
# ────────────────────────────────────────────────────────────────────
# QUAIS estados existem é a tabela account_status (o banco recusa o resto).
# QUAIS transições são permitidas é este dicionário — regra de negócio,
# então mora no controller. O que não está aqui é proibido (409).
#
# Estados sem entrada no dicionário não têm saída:
#   • REJECTED fica como registro de auditoria (trilha de PLD);
#   • CLOSED é final, e conta encerrada não recebe transação;
#   • REQUESTED existe na lista, mas hoje nenhuma conta nasce nele.
# BLOCKED → ACTIVE é decisão do time: bloqueio é reversível (ex.: fraude
# descartada).
ALLOWED_TRANSITIONS = {
    AccountStatus.PENDING: {AccountStatus.ACTIVE, AccountStatus.REJECTED},
    AccountStatus.ACTIVE: {AccountStatus.BLOCKED, AccountStatus.CLOSED},
    AccountStatus.BLOCKED: {AccountStatus.ACTIVE, AccountStatus.CLOSED},
}


class AccountController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_repository = AccountRepository(self.context)
        self.ledger_repository = LedgerRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)

    def get_by_id(self, raw_account_id: str) -> dict:
        account = self._get_account_or_raise(raw_account_id)
        return AccountDTO.obj_to_dict(account)

    @retry_on_deadlock()
    def update_status(self, raw_account_id: str, new_status: str, reason: str) -> dict:
        """Muda o status da conta, conferindo a máquina de estados.

        A conta é travada ANTES da checagem. Sem o lock, um PIX poderia
        cair entre o "saldo é zero" e o "encerrada", e a conta fecharia
        com dinheiro dentro.

        Transição recusada não grava evento: o histórico conta o que
        aconteceu, não o que foi tentado.
        """
        account_key = parse_uuid(raw_account_id)
        locked = self.account_repository.lock_customer_accounts_by_key([account_key])

        account = locked.get(account_key)
        if account is None:
            raise AccountNotFound(raw_account_id)

        old_status = account.status.enumerator
        if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
            raise InvalidStatusTransition(old_status, new_status)

        if new_status == AccountStatus.CLOSED:
            self._check_can_close(account)

        self.account_repository.update_status(account, new_status, reason)
        self.outbox_repository.add(
            OutboxEvent.ACCOUNT_STATUS_CHANGED,
            "account",
            account,
            {"from": old_status, "to": new_status, "reason": reason},
        )

        self.session.commit()

        return AccountDTO.obj_to_dict(account)

    def get_statement(self, raw_account_id: str, limit: int, cursor: str) -> dict:
        account = self._get_account_or_raise(raw_account_id)

        try:
            after = decode_cursor(cursor)
            if after is not None:
                int(after[1])
        except (ValueError, TypeError, UnicodeDecodeError):
            raise InvalidParameter("cursor is not valid")

        entries = self.ledger_repository.list_statement(account.id, limit, after)

        next_cursor = None
        if len(entries) > limit:
            entries = entries[:limit]
            last = entries[-1]
            next_cursor = encode_cursor(last.created_at, last.id)

        return {
            "account_id": str(account.key),
            "balance": account.balance,
            "held_balance": account.held_balance,
            "available_balance": account.available_balance,
            "items": AccountDTO.statement_items(entries, self.ledger_repository.reference_keys(entries)),
            "next_cursor": next_cursor,
        }

    def _check_can_close(self, account: Account) -> None:
        if account.balance != 0:
            raise AccountCannotBeClosed(f"balance is {account.balance}, must be 0")

        if account.held_balance != 0:
            raise AccountCannotBeClosed(f"held balance is {account.held_balance}, must be 0")

        if self.account_repository.has_active_loan(account.id):
            raise AccountCannotBeClosed("there is an active loan")

    def _get_account_or_raise(self, raw_account_id: str) -> Account:
        account_key = parse_uuid(raw_account_id)
        account = None

        if account_key is not None:
            account = self.account_repository.get_customer_account(account_key)

        if account is None:
            raise AccountNotFound(raw_account_id)

        return account