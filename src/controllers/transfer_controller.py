from typing import Tuple
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import TransferDTO
from constants import OWN_ISPB
from errors import (
    AccountNotActive,
    AccountNotFound,
    EndToEndIdAlreadyUsed,
    IdempotencyConflict,
    IdempotencyKeyRequired,
    IncomingTransferNotFound,
    IncomingTransferNotReversible,
    InsufficientBalance,
    InvalidParameter,
    InvalidPixMessage,
    InvalidScheduleDate,
    InvalidTargetAccount,
    NightLimitExceeded,
    PixKeyInquiryExpired,
    PixKeyInquiryNotFound,
    PixKeyMismatch,
    ReversalExceedsReceived,
    ReversalWindowExpired,
    SameAccountTransfer,
    TedOutsideWindow,
    TransferCannotBeCanceled,
    TransferNotFound,
)
from models import (
    Account,
    AccountStatus,
    IncomingTransfer,
    IncomingTransferStatus,
    LedgerEntry,
    OutboxEvent,
    Transfer,
    TransferStatus,
)

from repositories import (
    AccountRepository,
    CalendarRepository,
    IncomingTransferRepository,
    LedgerLeg,
    LedgerRepository,
    OutboxRepository,
    PixKeyRepository,
    TransferRepository,
)
from utils.cursor import decode_cursor, encode_cursor
from utils.db_retry import retry_on_deadlock
from utils.idempotency import is_valid_idempotency_key, request_hash
from utils.ids import parse_uuid
from utils.night_window import night_window_start
from utils.pix import REVERSAL_PREFIX, generate_end_to_end_id, has_emoji

# Janela da TED (STR): dia útil, das 6h30 às 17h, horário de Brasília.
TED_WINDOW_START = time(6, 30)
TED_WINDOW_END = time(17, 0)
 
# Devolução de Pix recebido: até 90 dias depois do recebimento (QI PXT000015).
REVERSAL_WINDOW_DAYS = 90
 
# Status em que a conta de destino ainda recebe (mesma regra do webhook do SPI).
CAN_RECEIVE = (AccountStatus.ACTIVE, AccountStatus.BLOCKED)
 


class TransferController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.transfer_repository = TransferRepository(self.context)
        self.account_repository = AccountRepository(self.context)
        self.ledger_repository = LedgerRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)

    @retry_on_deadlock()
    def create(self, payload: dict, idempotency_key: str) -> Tuple[dict, bool]:
        """Cria a transferência. Devolve (transferência, foi_criada_agora).

        `foi_criada_agora` é False quando o pedido é a REPETIÇÃO de um que
        já foi processado: aí nada é gravado de novo e a resposta é a do
        original. É o resource quem traduz isso em 201 ou 200.

        ────────────────────────────────────────────────────────────────
        A ORDEM, E POR QUE ELA É ESTA
        ────────────────────────────────────────────────────────────────
          1. idempotência (antes de tudo: repetição não reavalia regra)
          2. travar origem e destino, em ordem de id
          3. idempotência DE NOVO, já com o lock na mão
          4. status das duas contas
          5. tarifa, saldo e limite noturno
          6. gravar transferência + lançamento + evento, e commit

        O passo 3 existe por causa da corrida mais comum em pagamento: o
        cliente clica duas vezes. As duas requisições passam pelo passo 1
        ao mesmo tempo (nenhuma achou nada), uma pega o lock, a outra
        espera. Quando a segunda finalmente entra, a primeira já gravou —
        e o passo 3 enxerga isso antes de debitar de novo.

        O saldo só é lido DEPOIS do lock. Ler antes e travar depois é o
        bug clássico de saque duplo: duas requisições leem R$ 100, as
        duas aprovam R$ 80, e a conta fica em −R$ 60.
        """
        if not is_valid_idempotency_key(idempotency_key):
            raise IdempotencyKeyRequired()

        payload_hash = request_hash(payload)

        replay = self._find_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        source_id = parse_uuid(payload["source_account_id"])
        destination_id = parse_uuid(payload["destination"]["account_id"])

        if source_id is None:
            raise AccountNotFound(payload["source_account_id"])

        if destination_id is None:
            raise AccountNotFound(payload["destination"]["account_id"])

        if source_id == destination_id:
            raise SameAccountTransfer()

        locked = self.account_repository.lock_customer_accounts([source_id, destination_id])

        replay = self._find_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        source = locked.get(source_id)
        destination = locked.get(destination_id)

        if source is None:
            raise AccountNotFound(source_id)

        if destination is None:
            raise AccountNotFound(destination_id)

        if source.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(source.id, source.status.enumerator)

        if destination.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(destination.id, destination.status.enumerator)

        amount = payload["amount"]
        fee = self.transfer_repository.current_fee(Transfer.TEF, source.customer.type)

        if amount + fee > source.available_balance:
            raise InsufficientBalance(amount + fee, source.available_balance)

        self._check_night_limit(source, amount)

        try:
            transfer = self.transfer_repository.create_tef(
                idempotency_key, payload_hash, source, destination, amount, fee
            )
        except IntegrityError:
            # Mesma chave gravada por uma requisição concorrente que não
            # disputava estas contas (payload diferente, outras contas).
            self.session.rollback()
            replay = self._find_replay(idempotency_key, payload_hash)
            if replay is not None:
                return replay, False
            raise

        legs = [
            LedgerLeg(source, -amount, LedgerEntry.TEF_SENT, Transfer.TEF),
            LedgerLeg(destination, amount, LedgerEntry.TEF_RECEIVED, Transfer.TEF),
        ]

        if fee > 0:
            fee_revenue = self.account_repository.get_internal(Account.FEE_REVENUE)
            legs.append(LedgerLeg(source, -fee, LedgerEntry.TRANSFER_FEE, Transfer.TEF))
            legs.append(LedgerLeg(fee_revenue, fee, LedgerEntry.TRANSFER_FEE, Transfer.TEF))

        self.ledger_repository.post(legs, LedgerEntry.REF_TRANSFER, transfer.id)

        self.outbox_repository.add(
            OutboxEvent.TRANSFER_COMPLETED,
            "transfer",
            transfer.id,
            {"method": Transfer.TEF, "amount": amount, "fee": fee},
        )

        self.session.commit()

        return TransferDTO.obj_to_dict(transfer), True

    def get_by_id(self, raw_transfer_id: str) -> dict:
        transfer_id = parse_uuid(raw_transfer_id)
        transfer = None

        if transfer_id is not None:
            transfer = self.transfer_repository.get_by_id(transfer_id)

        if transfer is None:
            raise TransferNotFound(raw_transfer_id)

        return TransferDTO.obj_to_dict(transfer)

    def list_by_account(self, raw_account_id: str, statuses: list, limit: int, cursor: str) -> dict:
        account_id = parse_uuid(raw_account_id)
        account = None
        if account_id is not None:
            account = self.account_repository.get_customer_account(account_id)

        if account is None:
            raise AccountNotFound(raw_account_id)

        try:
            after = decode_cursor(cursor)
            if after is not None and parse_uuid(after[1]) is None:
                raise ValueError("cursor id is not a uuid")
        except (ValueError, TypeError, UnicodeDecodeError):
            raise InvalidParameter("cursor is not valid")

        transfers = self.transfer_repository.list_by_account(account.id, statuses, limit, after)

        next_cursor = None
        if len(transfers) > limit:
            transfers = transfers[:limit]
            last = transfers[-1]
            next_cursor = encode_cursor(last.created_at, last.id)

        return {"items": TransferDTO.list_obj_to_list_dict(transfers), "next_cursor": next_cursor}

    def _find_replay(self, idempotency_key: str, payload_hash: str):
        existing = self.transfer_repository.get_by_idempotency_key(idempotency_key)

        if existing is None:
            return None

        if existing.request_hash != payload_hash:
            raise IdempotencyConflict(idempotency_key)

        return TransferDTO.obj_to_dict(existing)

    def _check_night_limit(self, source: Account, amount: int) -> None:
        window_start = night_window_start(self.transfer_repository.local_now())

        if window_start is None:
            return

        already_used = self.transfer_repository.outflow_since(source.id, window_start)

        if already_used + amount > NIGHT_LIMIT:
            raise NightLimitExceeded(NIGHT_LIMIT, already_used)