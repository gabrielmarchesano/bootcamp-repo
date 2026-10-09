from typing import Optional
from uuid import UUID

from database import Context
from models import IncomingTransfer, IncomingTransferStatus
from repositories.enumerator_repository import EnumeratorRepository


class IncomingTransferRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

    def get_by_key(self, incoming_transfer_key: UUID) -> Optional[IncomingTransfer]:
        return self.session.query(IncomingTransfer).filter(IncomingTransfer.key == incoming_transfer_key).first()

    def get_by_external_id(self, rail: str, external_id: str) -> IncomingTransfer:
        return (
            self.session.query(IncomingTransfer)
            .filter(IncomingTransfer.rail == rail, IncomingTransfer.external_id == external_id)
            .first()
        )

    def create(
        self,
        rail: str,
        payload: dict,
        destination_account_id,
        status: str,
        pix_transfer_type: str = None,
        original_transfer_id=None,
    ) -> IncomingTransfer:
        sender = payload.get("sender", {})

        incoming = IncomingTransfer()
        incoming.rail = rail
        incoming.pix_transfer_type = pix_transfer_type
        incoming.external_id = payload["external_id"]
        incoming.destination_account_id = destination_account_id
        incoming.amount = payload["amount"]
        incoming.sender_name = sender.get("name")
        incoming.sender_document = sender.get("document")
        incoming.sender_ispb = sender.get("ispb")
        incoming.receiver_pix_key = payload.get("receiver_pix_key")
        incoming.pix_message = payload.get("pix_message")
        incoming.original_transfer_id = original_transfer_id
        incoming.status = self.enumerators.get(IncomingTransferStatus, status)

        self.session.add(incoming)
        self.session.flush()
        return incoming
