from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import TransferDTO
from models import Account, AccountStatus, IncomingTransfer, IncomingTransferStatus, LedgerEntry, OutboxEvent, Transfer
from repositories import AccountRepository, IncomingTransferRepository, LedgerLeg, LedgerRepository, OutboxRepository
from utils.db_retry import retry_on_deadlock

# Status em que a conta ainda RECEBE dinheiro. BLOCKED recebe: bloqueio é
# sobre o cliente movimentar, não sobre terceiros pagarem a ele (ex.: o
# cliente sob análise de fraude continua recebendo o salário). CLOSED,
# estado final, não recebe: a entrada vira devolução.
CAN_RECEIVE = (AccountStatus.ACTIVE, AccountStatus.BLOCKED)


class WebhookController(BaseController):
    """Entradas vindas dos trilhos (SPI agora; STR no sprint de TED).

    Toda resposta é 200, inclusive para repetição e para devolução. O
    trilho só quer saber se a mensagem foi RECEBIDA; o que fizemos com ela
    é assunto nosso. Responder 4xx faria o SPI reenviar a mesma mensagem
    em loop.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.incoming_repository = IncomingTransferRepository(self.context)
        self.account_repository = AccountRepository(self.context)
        self.ledger_repository = LedgerRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)

    @retry_on_deadlock()
    def spi_received(self, payload: dict) -> dict:
        """PIX recebido: credita a conta, ou registra a devolução.

        Idempotente pelo `external_id` (o endToEndId do PIX): o SPI pode
        entregar a mesma mensagem mais de uma vez, e o crédito só pode
        acontecer uma.
        """
        external_id = payload["external_id"]

        existing = self.incoming_repository.get_by_external_id(IncomingTransfer.SPI, external_id)
        if existing is not None:
            return TransferDTO.incoming_to_dict(existing)

        destination = payload["destination_account"]
        account = self.account_repository.get_customer_account_by_number(destination["branch"], destination["number"])

        locked = {}
        if account is not None:
            locked = self.account_repository.lock_customer_accounts([account.id])
            account = locked.get(account.id)

        # Re-checagem com o lock na mão: mesma razão do passo 3 da TEF.
        existing = self.incoming_repository.get_by_external_id(IncomingTransfer.SPI, external_id)
        if existing is not None:
            return TransferDTO.incoming_to_dict(existing)

        if account is None or account.status.enumerator not in CAN_RECEIVE:
            status = IncomingTransferStatus.RETURNED
            account_id = account.id if account is not None else None
        else:
            status = IncomingTransferStatus.CREDITED
            account_id = account.id

        try:
            incoming = self.incoming_repository.create(IncomingTransfer.SPI, payload, account_id, status)
        except IntegrityError:
            self.session.rollback()
            existing = self.incoming_repository.get_by_external_id(IncomingTransfer.SPI, external_id)
            return TransferDTO.incoming_to_dict(existing)

        if status == IncomingTransferStatus.CREDITED:
            spi_settlement = self.account_repository.get_internal(Account.SPI_SETTLEMENT)
            amount = payload["amount"]

            legs = [
                LedgerLeg(spi_settlement, -amount, LedgerEntry.PIX_RECEIVED, Transfer.PIX, external_id),
                LedgerLeg(account, amount, LedgerEntry.PIX_RECEIVED, Transfer.PIX, external_id),
            ]
            self.ledger_repository.post(legs, LedgerEntry.REF_INCOMING_TRANSFER, incoming.id)

            event_type = OutboxEvent.INCOMING_TRANSFER_CREDITED
        else:
            # Devolução: no SPI de verdade, aqui sairia a mensagem de
            # devolução (pacs.004). No mock, fica o registro e o evento.
            event_type = OutboxEvent.INCOMING_TRANSFER_RETURNED

        self.outbox_repository.add(
            event_type,
            "incoming_transfer",
            incoming.id,
            {"rail": IncomingTransfer.SPI, "external_id": external_id, "amount": payload["amount"]},
        )

        self.session.commit()

        return TransferDTO.incoming_to_dict(incoming)