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

# Teto noturno em centavos (Res. BCB 142/2021), igual ao usado nos testes.
NIGHT_LIMIT = 100_000
 


class TransferController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.transfer_repository = TransferRepository(self.context)
        self.account_repository = AccountRepository(self.context)
        self.ledger_repository = LedgerRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)
        self.pix_key_repository = PixKeyRepository(self.context)
        self.incoming_repository = IncomingTransferRepository(self.context)
        self.calendar_repository = CalendarRepository(self.context)

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

        source_key = parse_uuid(payload["source_account_id"])
        destination_key = parse_uuid(payload["destination"]["account_id"])

        if source_key is None:
            raise AccountNotFound(payload["source_account_id"])

        if destination_key is None:
            raise AccountNotFound(payload["destination"]["account_id"])

        if source_key == destination_key:
            raise SameAccountTransfer()

        locked = self.account_repository.lock_customer_accounts_by_key([source_key, destination_key])

        replay = self._find_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        source = locked.get(source_key)
        destination = locked.get(destination_key)

        if source is None:
            raise AccountNotFound(source_key)

        if destination is None:
            raise AccountNotFound(destination_key)

        if source.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(source.key, source.status.enumerator)

        if destination.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(destination.key, destination.status.enumerator)

        amount = payload["amount"]
        fee = self.transfer_repository.current_fee(Transfer.TEF, source.customer.fee_segment)

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
            OutboxEvent.OUTGOING_TEF,
            "transfer",
            transfer,
            {"method": Transfer.TEF, "amount": amount, "fee": fee},
        )

        self.session.commit()

        return TransferDTO.obj_to_dict(transfer), True

    def get_by_id(self, raw_transfer_id: str) -> dict:
        transfer_key = parse_uuid(raw_transfer_id)
        transfer = None

        if transfer_key is not None:
            transfer = self.transfer_repository.get_by_key(transfer_key)

        if transfer is None:
            raise TransferNotFound(raw_transfer_id)

        return TransferDTO.obj_to_dict(transfer)

    def list_by_account(self, raw_account_id: str, statuses: list, limit: int, cursor: str) -> dict:
        account_key = parse_uuid(raw_account_id)
        account = None
        if account_key is not None:
            account = self.account_repository.get_customer_account(account_key)

        if account is None:
            raise AccountNotFound(raw_account_id)

        try:
            after = decode_cursor(cursor)
            if after is not None:
                int(after[1])
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

    # ── Pix de saída ────────────────────────────────────────────────

    @retry_on_deadlock()
    def create_pix(self, raw_account_id: str, payload: dict, idempotency_key: str) -> Tuple[dict, bool]:
        """Pix de saída, por chave ou manual. Devolve (transferência, foi_criada_agora).

        Mesma espinha da TEF: idempotência, lock da origem, idempotência de
        novo com o lock na mão, regras, grava e commita. Pix on-us nasce
        COMPLETED (201); Pix que vai pro trilho nasce SENT (202) e só
        liquida no webhook.
        """
        if not is_valid_idempotency_key(idempotency_key):
            raise IdempotencyKeyRequired()

        payload_hash = request_hash(payload)

        replay = self._find_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        pix_message = payload.get("pix_message")
        if has_emoji(pix_message):
            raise InvalidPixMessage()

        # Resolve origem e destino SEM lock para descobrir se é on-us; só então
        # trava as duas contas de uma vez, em ordem de id (igual à TEF), para
        # que dois Pix cruzados (A→B e B→A) não travem em sentidos opostos.
        source_key = parse_uuid(raw_account_id)
        unlocked_source = self.account_repository.get_customer_account(source_key) if source_key is not None else None
        if unlocked_source is None:
            raise AccountNotFound(raw_account_id)
        source_id = unlocked_source.id

        if payload["pix_transfer_type"] == Transfer.PIX_KEY:
            resolved = self._pix_key_fields(source_id, payload)
        else:
            resolved = self._pix_manual_fields(source_id, payload)

        destination_id = resolved.get("destination_account_id")
        lock_ids = [source_id] if destination_id is None else [source_id, destination_id]
        locked = self.account_repository.lock_customer_accounts(lock_ids)

        replay = self._find_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        source = locked.get(source_id)
        if source is None:
            raise AccountNotFound(raw_account_id)

        if source.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(source.key, source.status.enumerator)

        destination = locked.get(destination_id) if destination_id is not None else None

        amount = payload["amount"]
        fields = {"columns": resolved["columns"]}
        on_us = destination is not None
        fee = self.transfer_repository.current_fee(Transfer.PIX, source.customer.fee_segment)

        if amount + fee > source.available_balance:
            raise InsufficientBalance(amount + fee, source.available_balance)

        self._check_night_limit(source, amount)

        status = TransferStatus.COMPLETED if on_us else TransferStatus.SENT
        transfer_fields = dict(fields["columns"])
        transfer_fields["on_us"] = on_us
        transfer_fields["pix_message"] = pix_message

        try:
            transfer = self.transfer_repository.create_outgoing(
                idempotency_key,
                payload_hash,
                source,
                Transfer.PIX,
                amount,
                fee,
                status,
                **transfer_fields,
            )
        except IntegrityError:
            self.session.rollback()
            replay = self._find_replay(idempotency_key, payload_hash)
            if replay is not None:
                return replay, False
            # Dois Pix por chave disputando o mesmo e2e/consulta: um grava, o
            # outro bate no UNIQUE (end_to_end_id / pix_key_inquiry_id). O e2e
            # é de uso único, então a corrida perdedora é 409, não 500.
            if payload["pix_transfer_type"] == Transfer.PIX_KEY:
                raise EndToEndIdAlreadyUsed(payload["end_to_end_id"])
            raise

        legs = [LedgerLeg(source, -amount, LedgerEntry.PIX_SENT, Transfer.PIX, transfer.end_to_end_id)]
        if on_us:
            legs.append(LedgerLeg(destination, amount, LedgerEntry.PIX_RECEIVED, Transfer.PIX, transfer.end_to_end_id))
        else:
            settlement = self.account_repository.get_internal(Account.SPI_SETTLEMENT)
            legs.append(LedgerLeg(settlement, amount, LedgerEntry.PIX_SENT, Transfer.PIX, transfer.end_to_end_id))

        if fee > 0:
            fee_revenue = self.account_repository.get_internal(Account.FEE_REVENUE)
            legs.append(LedgerLeg(source, -fee, LedgerEntry.TRANSFER_FEE, Transfer.PIX))
            legs.append(LedgerLeg(fee_revenue, fee, LedgerEntry.TRANSFER_FEE, Transfer.PIX))

        self.ledger_repository.post(legs, LedgerEntry.REF_TRANSFER, transfer.id)
        self._pix_outbox(transfer)
        self.session.commit()

        return TransferDTO.obj_to_dict(transfer), True

    @retry_on_deadlock()
    def create_pix_reversal(
        self, raw_account_id: str, raw_incoming_transfer_id: str, payload: dict, idempotency_key: str
    ) -> Tuple[dict, bool]:
        """Devolução de um Pix RECEBIDO (QI: POST .../reversals).

        Sai sempre pelo trilho (nunca on-us), aponta para a entrada original
        e nasce SENT. A soma das devoluções não pode passar do valor
        recebido (QIT001026).
        """
        if not is_valid_idempotency_key(idempotency_key):
            raise IdempotencyKeyRequired()

        payload_hash = request_hash(payload)

        replay = self._find_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        source = self._lock_active_source(raw_account_id)

        replay = self._find_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        incoming_key = parse_uuid(raw_incoming_transfer_id)
        incoming = self.incoming_repository.get_by_key(incoming_key) if incoming_key is not None else None

        if incoming is None or incoming.destination_account_id != source.id:
            raise IncomingTransferNotFound(raw_incoming_transfer_id)

        # Só Pix se devolve (TED devolvida é outro fluxo), e devolução de
        # devolução não existe.
        if incoming.rail != IncomingTransfer.SPI:
            raise IncomingTransferNotReversible("only Pix can be reversed")

        if incoming.pix_transfer_type == IncomingTransfer.PIX_REVERSAL:
            raise IncomingTransferNotReversible("it is already a reversal")

        if incoming.status.enumerator != IncomingTransferStatus.CREDITED:
            raise IncomingTransferNotReversible(incoming.status.enumerator)

        if datetime.now(timezone.utc) - incoming.received_at > timedelta(days=REVERSAL_WINDOW_DAYS):
            raise ReversalWindowExpired()

        amount = payload["amount"]
        reversed_total = self.transfer_repository.reversed_total(incoming.id)
        if reversed_total + amount > incoming.amount:
            raise ReversalExceedsReceived(reversed_total + amount, incoming.amount)

        # A devolução tira dinheiro da conta como qualquer saída: saldo é lido
        # depois do lock (o _lock_active_source já travou a conta).
        if amount > source.available_balance:
            raise InsufficientBalance(amount, source.available_balance)

        fields = {
            "pix_transfer_type": Transfer.PIX_REVERSAL,
            "destination_ispb": incoming.sender_ispb,
            "original_incoming_transfer_id": incoming.id,
            "reversal_reason": payload["reversal_reason"],
            "end_to_end_id": generate_end_to_end_id(prefix=REVERSAL_PREFIX),
            "on_us": False,
        }

        try:
            transfer = self.transfer_repository.create_outgoing(
                idempotency_key, payload_hash, source, Transfer.PIX, amount, 0, TransferStatus.SENT, **fields
            )
        except IntegrityError:
            self.session.rollback()
            replay = self._find_replay(idempotency_key, payload_hash)
            if replay is not None:
                return replay, False
            raise

        settlement = self.account_repository.get_internal(Account.SPI_SETTLEMENT)
        legs = [
            LedgerLeg(source, -amount, LedgerEntry.PIX_REVERSAL_SENT, Transfer.PIX, transfer.end_to_end_id),
            LedgerLeg(settlement, amount, LedgerEntry.PIX_REVERSAL_SENT, Transfer.PIX, transfer.end_to_end_id),
        ]
        self.ledger_repository.post(legs, LedgerEntry.REF_TRANSFER, transfer.id)
        self._pix_outbox(transfer)
        self.session.commit()

        return TransferDTO.obj_to_dict(transfer), True

    # ── TED de saída ─────────────────────────────────────────────────

    @retry_on_deadlock()
    def create_ted(self, raw_account_id: str, payload: dict, idempotency_key: str) -> Tuple[dict, bool]:
        """TED de saída: imediata (dentro da janela do STR) ou agendada.

        Imediata debita valor + tarifa e nasce SENT; agendada não debita e
        nasce SCHEDULED (o débito fica para o job no dia). Nunca on-us: TED
        é trilho externo.
        """
        if not is_valid_idempotency_key(idempotency_key):
            raise IdempotencyKeyRequired()

        payload_hash = request_hash(payload)

        replay = self._find_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        source = self._lock_active_source(raw_account_id)

        replay = self._find_replay(idempotency_key, payload_hash)
        if replay is not None:
            return replay, False

        target = payload["target_account"]
        if target["ispb"] == OWN_ISPB:
            raise InvalidTargetAccount("TED must go to another institution")

        amount = payload["amount"]
        fields = {
            "destination_ispb": target["ispb"],
            "destination_branch": target["branch"],
            "destination_account": target["number"],
            "destination_account_digit": target.get("digit"),
            "destination_account_type": target["account_type"],
            "destination_document": target["document"],
            "destination_name": target["name"],
            "on_us": False,
        }

        schedule_date = payload.get("schedule_date")
        if schedule_date is not None:
            scheduled_for = self._parse_future_business_day(schedule_date)
            fields["scheduled_for"] = scheduled_for
            transfer = self.transfer_repository.create_outgoing(
                idempotency_key, payload_hash, source, Transfer.TED, amount, 0, TransferStatus.SCHEDULED, **fields
            )
            self._ted_outbox(transfer)
            self.session.commit()
            return TransferDTO.obj_to_dict(transfer), True

        if not self._ted_window_open():
            raise TedOutsideWindow()

        fee = self.transfer_repository.current_fee(Transfer.TED, source.customer.fee_segment)
        if amount + fee > source.available_balance:
            raise InsufficientBalance(amount + fee, source.available_balance)

        self._check_night_limit(source, amount)

        fields["str_control_number"] = self.transfer_repository.generate_str_control_number()

        try:
            transfer = self.transfer_repository.create_outgoing(
                idempotency_key, payload_hash, source, Transfer.TED, amount, fee, TransferStatus.SENT, **fields
            )
        except IntegrityError:
            self.session.rollback()
            replay = self._find_replay(idempotency_key, payload_hash)
            if replay is not None:
                return replay, False
            raise

        settlement = self.account_repository.get_internal(Account.STR_SETTLEMENT)
        legs = [
            LedgerLeg(source, -amount, LedgerEntry.TED_SENT, Transfer.TED, transfer.str_control_number),
            LedgerLeg(settlement, amount, LedgerEntry.TED_SENT, Transfer.TED, transfer.str_control_number),
        ]
        if fee > 0:
            fee_revenue = self.account_repository.get_internal(Account.FEE_REVENUE)
            legs.append(LedgerLeg(source, -fee, LedgerEntry.TRANSFER_FEE, Transfer.TED))
            legs.append(LedgerLeg(fee_revenue, fee, LedgerEntry.TRANSFER_FEE, Transfer.TED))

        self.ledger_repository.post(legs, LedgerEntry.REF_TRANSFER, transfer.id)
        self._ted_outbox(transfer)
        self.session.commit()

        return TransferDTO.obj_to_dict(transfer), True

    # ── cancelamento ─────────────────────────────────────────────────

    @retry_on_deadlock()
    def cancel(self, raw_transfer_id: str) -> dict:
        """SCHEDULED → CANCELED. Qualquer outro status: 409 (QIT001028)."""
        transfer_key = parse_uuid(raw_transfer_id)
        transfer = self.transfer_repository.get_by_key(transfer_key) if transfer_key is not None else None

        if transfer is None:
            raise TransferNotFound(raw_transfer_id)

        self.account_repository.lock_customer_accounts([transfer.source_account_id])
        transfer = self.transfer_repository.lock(transfer)

        if transfer.status.enumerator != TransferStatus.SCHEDULED:
            raise TransferCannotBeCanceled(transfer.status.enumerator)

        self.transfer_repository.update_status(transfer, TransferStatus.CANCELED, "customer request")
        self._ted_outbox(transfer)
        self.session.commit()

        return TransferDTO.obj_to_dict(transfer)

    # ── TED agendada (job run_scheduled_teds) ───────────────────────

    @retry_on_deadlock()
    def execute_scheduled_ted(self, transfer_id: int) -> str:
        """Executa uma TED SCHEDULED: volta ao começo do fluxo da TED imediata.

        Mesma ordem de lock (conta → transferência) e as mesmas regras de
        status, tarifa e saldo. Sem saldo ou com a conta fora de ACTIVE, a
        TED vira FAILED — o cliente agendou, mas o dinheiro não estava lá.
        Idempotente: se já não está SCHEDULED, não faz nada.

        Devolve o desfecho: SENT, FAILED ou SKIPPED.
        """
        transfer = self.session.get(Transfer, transfer_id)
        if transfer is None:
            return "SKIPPED"

        locked = self.account_repository.lock_customer_accounts([transfer.source_account_id])
        transfer = self.transfer_repository.lock(transfer)

        if transfer.status.enumerator != TransferStatus.SCHEDULED:
            self.session.rollback()
            return "SKIPPED"

        source = locked.get(transfer.source_account_id)
        if source is None or source.status.enumerator != AccountStatus.ACTIVE:
            transfer.failure_reason = "ACCOUNT_NOT_ACTIVE"
            self.transfer_repository.update_status(transfer, TransferStatus.FAILED, "ACCOUNT_NOT_ACTIVE")
            self._ted_outbox(transfer)
            self.session.commit()
            return TransferStatus.FAILED

        fee = self.transfer_repository.current_fee(Transfer.TED, source.customer.fee_segment)
        if transfer.amount + fee > source.available_balance:
            transfer.failure_reason = "INSUFFICIENT_BALANCE"
            self.transfer_repository.update_status(transfer, TransferStatus.FAILED, "INSUFFICIENT_BALANCE")
            self._ted_outbox(transfer)
            self.session.commit()
            return TransferStatus.FAILED

        transfer.fee = fee
        transfer.str_control_number = self.transfer_repository.generate_str_control_number()
        self.transfer_repository.update_status(transfer, TransferStatus.SENT, "scheduled TED executed")

        settlement = self.account_repository.get_internal(Account.STR_SETTLEMENT)
        legs = [
            LedgerLeg(source, -transfer.amount, LedgerEntry.TED_SENT, Transfer.TED, transfer.str_control_number),
            LedgerLeg(settlement, transfer.amount, LedgerEntry.TED_SENT, Transfer.TED, transfer.str_control_number),
        ]
        if fee > 0:
            fee_revenue = self.account_repository.get_internal(Account.FEE_REVENUE)
            legs.append(LedgerLeg(source, -fee, LedgerEntry.TRANSFER_FEE, Transfer.TED))
            legs.append(LedgerLeg(fee_revenue, fee, LedgerEntry.TRANSFER_FEE, Transfer.TED))

        self.ledger_repository.post(legs, LedgerEntry.REF_TRANSFER, transfer.id)
        self._ted_outbox(transfer)
        self.session.commit()
        return TransferStatus.SENT

    def ted_window_open(self) -> bool:
        return self._ted_window_open()

    # ── auxiliares ───────────────────────────────────────────────────

    def _lock_active_source(self, raw_account_id: str) -> Account:
        """Resolve, trava e confere que a conta de origem está ativa."""
        account_key = parse_uuid(raw_account_id)
        if account_key is None:
            raise AccountNotFound(raw_account_id)

        locked = self.account_repository.lock_customer_accounts_by_key([account_key])
        source = locked.get(account_key)
        if source is None:
            raise AccountNotFound(raw_account_id)

        if source.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(source.key, source.status.enumerator)

        return source

    def _pix_key_fields(self, source_id, payload: dict) -> dict:
        """Colunas e destino de um Pix por chave, a partir da consulta ao DICT.

        Resolve SEM lock (a leitura é só para descobrir o destino e validar o
        e2e). Devolve o `destination_account_id` quando o Pix é on-us; quem
        trava as contas é o `create_pix`.
        """
        end_to_end_id = payload["end_to_end_id"]
        inquiry = self.pix_key_repository.get_inquiry(source_id, end_to_end_id)

        if inquiry is None:
            raise PixKeyInquiryNotFound(end_to_end_id)

        if inquiry.pix_key != payload["pix_key"]:
            raise PixKeyMismatch()

        now = self.transfer_repository.local_now()
        expires_at = inquiry.expires_at
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)
        if expires_at < now:
            raise PixKeyInquiryExpired(end_to_end_id)

        if self.transfer_repository.get_by_end_to_end_id(end_to_end_id) is not None:
            raise EndToEndIdAlreadyUsed(end_to_end_id)

        columns = {
            "pix_transfer_type": Transfer.PIX_KEY,
            "pix_key": inquiry.pix_key,
            "pix_key_inquiry_id": inquiry.id,
            "end_to_end_id": end_to_end_id,
            "destination_ispb": inquiry.ispb,
        }

        destination_account_id = inquiry.destination_account_id
        if destination_account_id is not None:
            columns["destination_account_id"] = destination_account_id

        return {"columns": columns, "destination_account_id": destination_account_id}

    def _pix_manual_fields(self, source_id, payload: dict) -> dict:
        """Colunas e destino de um Pix manual (QI target_account).

        Resolve SEM lock; devolve o `destination_account_id` quando bate numa
        conta nossa (on-us). Quem trava as contas é o `create_pix`.
        """
        target = payload["target_account"]
        destination = self.account_repository.get_customer_account_by_number(target["branch"], target["number"])

        if destination is not None and destination.id != source_id:
            holder = destination.customer
            # v7: `document` já é CPF ou CNPJ conforme o person_type do
            # titular — não existe mais holder.cpf/holder.cnpj/holder.type.
            if target["document"] != holder.document:
                raise InvalidTargetAccount("document does not match the account holder")
        else:
            destination = None

        columns = {
            "pix_transfer_type": Transfer.PIX_MANUAL,
            "end_to_end_id": generate_end_to_end_id(),
            "destination_ispb": target["ispb"],
            "destination_branch": target["branch"],
            "destination_account": target["number"],
            "destination_account_digit": target.get("digit"),
            "destination_account_type": target["account_type"],
            "destination_document": target["document"],
            "destination_name": target["name"],
        }

        destination_account_id = destination.id if destination is not None else None
        if destination_account_id is not None:
            columns["destination_account_id"] = destination_account_id

        return {"columns": columns, "destination_account_id": destination_account_id}

    def _parse_future_business_day(self, schedule_date: str) -> date:
        """Lê schedule_date e exige um dia útil DEPOIS de hoje (QIT001049)."""
        try:
            scheduled_for = date.fromisoformat(schedule_date)
        except (ValueError, TypeError):
            raise InvalidScheduleDate()

        today = self.calendar_repository.local_now().date()
        if scheduled_for <= today or not self.calendar_repository.is_business_day(scheduled_for):
            raise InvalidScheduleDate()

        return scheduled_for

    def _ted_window_open(self) -> bool:
        """Janela do STR: dia útil, das 6h30 às 17h (horário de Brasília)."""
        now = self.calendar_repository.local_now()
        if not self.calendar_repository.is_business_day(now.date()):
            return False
        return TED_WINDOW_START <= now.time() < TED_WINDOW_END

    def _pix_outbox(self, transfer: Transfer) -> None:
        self.outbox_repository.add(
            OutboxEvent.OUTGOING_PIX,
            "transfer",
            transfer,
            {
                "request_control_key": transfer.idempotency_key,
                "status": transfer.status.enumerator,
                "end_to_end_id": transfer.end_to_end_id,
                "pix_transfer_type": transfer.pix_transfer_type,
            },
        )

    def _ted_outbox(self, transfer: Transfer) -> None:
        self.outbox_repository.add(
            OutboxEvent.OUTGOING_TED,
            "transfer",
            transfer,
            {
                "request_control_key": transfer.idempotency_key,
                "status": transfer.status.enumerator,
                "str_control_number": transfer.str_control_number,
                "scheduled_for": transfer.scheduled_for.isoformat() if transfer.scheduled_for is not None else None,
            },
        )