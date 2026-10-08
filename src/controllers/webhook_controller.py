from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import TransferDTO
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
    IncomingTransferRepository,
    LedgerLeg,
    LedgerRepository,
    OutboxRepository,
    TransferRepository,
)
from utils.db_retry import retry_on_deadlock

# Status em que a conta ainda RECEBE dinheiro. BLOCKED recebe: bloqueio é
# sobre o cliente movimentar, não sobre terceiros pagarem a ele (ex.: o
# cliente sob análise de fraude continua recebendo o salário). CLOSED,
# estado final, não recebe: a entrada vira devolução.
CAN_RECEIVE = (AccountStatus.ACTIVE, AccountStatus.BLOCKED)

# Por trilho: a conta transitória e o tipo de lançamento da entrada.
RAILS = {
    IncomingTransfer.SPI: (Account.SPI_SETTLEMENT, LedgerEntry.PIX_RECEIVED, Transfer.PIX, OutboxEvent.INCOMING_PIX),
    IncomingTransfer.STR: (Account.STR_SETTLEMENT, LedgerEntry.TED_RECEIVED, Transfer.TED, OutboxEvent.INCOMING_TED),
}

IGNORED = "IGNORED"


class WebhookController(BaseController):
    """Mensagens vindas dos trilhos (SPI e STR, ambos mock).

    Toda resposta é 200, inclusive para repetição, devolução e mensagem
    sobre transferência que não conhecemos. O trilho só quer saber se a
    mensagem foi RECEBIDA; o que fizemos com ela é assunto nosso.
    Responder 4xx faria o trilho reenviar a mesma mensagem em loop.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.incoming_repository = IncomingTransferRepository(self.context)
        self.account_repository = AccountRepository(self.context)
        self.ledger_repository = LedgerRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)
        self.transfer_repository = TransferRepository(self.context)

    # ── SPI ──────────────────────────────────────────────────────────

    def spi(self, payload: dict) -> dict:
        event = payload["event"]

        if event == "RECEIVED":
            return self.received(IncomingTransfer.SPI, payload)

        if event == "SETTLED":
            transfer = self.transfer_repository.get_by_end_to_end_id(payload["end_to_end_id"])
            return self.settle(transfer, Transfer.PIX, payload["end_to_end_id"])

        transfer = self.transfer_repository.get_by_end_to_end_id(payload["end_to_end_id"])
        return self.reject_pix(transfer, payload)

    # ── STR ──────────────────────────────────────────────────────────

    def str_(self, payload: dict) -> dict:
        event = payload["event"]

        if event == "RECEIVED":
            return self.received(IncomingTransfer.STR, payload)

        transfer = self.transfer_repository.get_by_str_control_number(payload["str_control_number"])

        if event == "SETTLED":
            return self.settle(transfer, Transfer.TED, payload["str_control_number"])

        return self.return_ted(transfer, payload)

    # ── entrada (Pix ou TED recebidos, devolução de Pix nosso) ──────

    @retry_on_deadlock()
    def received(self, rail: str, payload: dict) -> dict:
        """Credita a conta, ou registra a devolução da entrada.

        Idempotente pelo `external_id` (endToEndId no SPI, número de
        controle no STR): o trilho pode entregar a mesma mensagem mais de
        uma vez, e o crédito só pode acontecer uma.

        Pix do tipo REVERSAL é a devolução de um Pix que NÓS enviamos (QI:
        `original_outgoing_pix_transfer`). Ele só é aceito se apontar para
        um Pix nosso já liquidado, voltar para a conta que pagou e não
        somar mais do que o valor original. Fora disso, vira RETURNED —
        não sabemos de quem é o dinheiro, então ele volta.
        """
        external_id = payload["external_id"]

        existing = self.incoming_repository.get_by_external_id(rail, external_id)
        if existing is not None:
            return TransferDTO.incoming_to_dict(existing)

        destination = payload["destination_account"]
        account = self.account_repository.get_customer_account_by_number(destination["branch"], destination["number"])

        if account is not None:
            locked = self.account_repository.lock_customer_accounts([account.id])
            account = locked.get(account.id)

        # Re-checagem com o lock na mão: mesma razão do passo 3 da TEF.
        existing = self.incoming_repository.get_by_external_id(rail, external_id)
        if existing is not None:
            return TransferDTO.incoming_to_dict(existing)

        pix_transfer_type = None
        original = None
        if rail == IncomingTransfer.SPI:
            pix_transfer_type = payload.get("pix_transfer_type", IncomingTransfer.PIX_MANUAL)

        can_credit = account is not None and account.status.enumerator in CAN_RECEIVE

        if pix_transfer_type == IncomingTransfer.PIX_REVERSAL:
            original = self._original_for_reversal(payload, account)
            if original is None:
                # Devolução que não aponta para um Pix nosso válido não pode
                # nascer como REVERSAL (o CHECK exige o original): fica
                # registrada como entrada comum e volta para quem mandou.
                pix_transfer_type = IncomingTransfer.PIX_MANUAL
                can_credit = False

        status = IncomingTransferStatus.CREDITED if can_credit else IncomingTransferStatus.RETURNED
        account_id = account.id if account is not None else None

        try:
            incoming = self.incoming_repository.create(
                rail,
                payload,
                account_id,
                status,
                pix_transfer_type=pix_transfer_type,
                original_transfer_id=original.id if original is not None else None,
            )
        except IntegrityError:
            self.session.rollback()
            existing = self.incoming_repository.get_by_external_id(rail, external_id)
            return TransferDTO.incoming_to_dict(existing)

        settlement_code, entry_type, method, event_type = RAILS[rail]
        if original is not None:
            entry_type = LedgerEntry.PIX_REVERSAL_RECEIVED

        if status == IncomingTransferStatus.CREDITED:
            settlement = self.account_repository.get_internal(settlement_code)
            amount = payload["amount"]

            legs = [
                LedgerLeg(settlement, -amount, entry_type, method, external_id),
                LedgerLeg(account, amount, entry_type, method, external_id),
            ]
            self.ledger_repository.post(legs, LedgerEntry.REF_INCOMING_TRANSFER, incoming.id)

        # Devolução: no trilho de verdade, aqui sairia a mensagem de
        # devolução (pacs.004 no SPI). No mock, fica o registro e o evento.
        self.outbox_repository.add(
            event_type,
            "incoming_transfer",
            incoming,
            {
                "rail": rail,
                "external_id": external_id,
                "amount": payload["amount"],
                "status": status,
                "pix_transfer_type": pix_transfer_type,
                "original_transfer_id": str(original.key) if original is not None else None,
            },
        )

        self.session.commit()

        return TransferDTO.incoming_to_dict(incoming)

    def _original_for_reversal(self, payload: dict, account):
        original = self.transfer_repository.get_by_end_to_end_id(payload.get("original_end_to_end_id") or "")

        if original is None or original.method != Transfer.PIX or account is None:
            return None

        if original.pix_transfer_type == Transfer.PIX_REVERSAL:
            return None

        if original.status.enumerator != TransferStatus.COMPLETED or original.source_account_id != account.id:
            return None

        already_returned = sum(
            item.amount
            for item in self.session.query(IncomingTransfer).filter(IncomingTransfer.original_transfer_id == original.id)
            if item.status.enumerator == IncomingTransferStatus.CREDITED
        )
        if already_returned + payload["amount"] > original.amount:
            return None

        return original

    # ── confirmação de saída ─────────────────────────────────────────

    @retry_on_deadlock()
    def settle(self, transfer, method: str, external_id: str) -> dict:
        """O trilho confirmou a liquidação: SENT → COMPLETED. Repetição não muda nada."""
        if transfer is None or transfer.method != method:
            return {"result": IGNORED, "external_id": external_id}

        self.account_repository.lock_customer_accounts([transfer.source_account_id])
        transfer = self.transfer_repository.lock(transfer)

        if transfer.status.enumerator == TransferStatus.SENT:
            self.transfer_repository.update_status(transfer, TransferStatus.COMPLETED, f"{method} settled")
            self._outbox(transfer)
            self.session.commit()

        return TransferDTO.obj_to_dict(transfer)

    @retry_on_deadlock()
    def reject_pix(self, transfer, payload: dict) -> dict:
        """O SPI recusou: SENT → REJECTED, e o dinheiro volta (valor e tarifa).

        O código de erro do trilho fica em `failure_code`, como o `error_code`
        do webhook da QI (ex.: PXT000132, conta de destino inexistente).
        """
        if transfer is None or transfer.method != Transfer.PIX:
            return {"result": IGNORED, "external_id": payload["end_to_end_id"]}

        locked = self.account_repository.lock_customer_accounts([transfer.source_account_id])
        transfer = self.transfer_repository.lock(transfer)

        if transfer.status.enumerator != TransferStatus.SENT:
            return TransferDTO.obj_to_dict(transfer)

        transfer.failure_code = payload["error_code"]
        transfer.failure_reason = payload.get("error_description")
        self.transfer_repository.update_status(transfer, TransferStatus.REJECTED, payload["error_code"])

        source = locked[transfer.source_account_id]
        self._post_reversal(source, transfer, Account.SPI_SETTLEMENT, refund_fee=True)
        self._outbox(transfer)
        self.session.commit()

        return TransferDTO.obj_to_dict(transfer)

    @retry_on_deadlock()
    def return_ted(self, transfer, payload: dict) -> dict:
        """O banco de destino devolveu a TED: SENT|COMPLETED → RETURNED.

        Volta o valor, não a tarifa: a TED foi executada; quem recusou foi o
        outro banco. É a mesma leitura da QI (`refusal_reason` no webhook).
        """
        if transfer is None or transfer.method != Transfer.TED:
            return {"result": IGNORED, "external_id": payload["str_control_number"]}

        locked = self.account_repository.lock_customer_accounts([transfer.source_account_id])
        transfer = self.transfer_repository.lock(transfer)

        if transfer.status.enumerator not in (TransferStatus.SENT, TransferStatus.COMPLETED):
            return TransferDTO.obj_to_dict(transfer)

        transfer.failure_reason = payload.get("reason")
        self.transfer_repository.update_status(transfer, TransferStatus.RETURNED, payload.get("reason"))

        source = locked[transfer.source_account_id]
        self._post_reversal(source, transfer, Account.STR_SETTLEMENT, refund_fee=False)
        self._outbox(transfer)
        self.session.commit()

        return TransferDTO.obj_to_dict(transfer)

    def _post_reversal(self, source: Account, transfer, settlement_code: str, refund_fee: bool) -> None:
        """Estorno = lançamento novo, ao contrário. O original nunca é editado."""
        settlement = self.account_repository.get_internal(settlement_code)
        external_id = transfer.end_to_end_id or transfer.str_control_number
        legs = [
            LedgerLeg(settlement, -transfer.amount, LedgerEntry.REVERSAL, transfer.method, external_id),
            LedgerLeg(source, transfer.amount, LedgerEntry.REVERSAL, transfer.method, external_id),
        ]
        if refund_fee and transfer.fee > 0:
            fee_revenue = self.account_repository.get_internal(Account.FEE_REVENUE)
            legs.append(LedgerLeg(fee_revenue, -transfer.fee, LedgerEntry.REVERSAL, transfer.method))
            legs.append(LedgerLeg(source, transfer.fee, LedgerEntry.REVERSAL, transfer.method))
        self.ledger_repository.post(legs, LedgerEntry.REF_TRANSFER, transfer.id)

    def _outbox(self, transfer) -> None:
        event_type = OutboxEvent.OUTGOING_PIX if transfer.method == Transfer.PIX else OutboxEvent.OUTGOING_TED
        self.outbox_repository.add(
            event_type,
            "transfer",
            transfer,
            {
                "request_control_key": transfer.idempotency_key,
                "status": transfer.status.enumerator,
                "end_to_end_id": transfer.end_to_end_id,
                "str_control_number": transfer.str_control_number,
                "error_code": transfer.failure_code,
            },
        )