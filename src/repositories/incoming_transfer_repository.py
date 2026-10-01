from database import Context
from models import IncomingTransfer


class IncomingTransferRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_external_id(self, rail: str, external_id: str) -> IncomingTransfer:
        return (
            self.session.query(IncomingTransfer)
            .filter(IncomingTransfer.rail == rail, IncomingTransfer.external_id == external_id)
            .first()
        )

    def create(self, rail: str, payload: dict, destination_account_id, status: str) -> IncomingTransfer:
        sender = payload.get("sender", {})

        incoming = IncomingTransfer()
        incoming.rail = rail
        incoming.external_id = payload["external_id"]
        incoming.destination_account_id = destination_account_id
        incoming.amount = payload["amount"]
        incoming.sender_name = sender.get("name")
        incoming.sender_document = sender.get("document")
        incoming.sender_ispb = sender.get("ispb")
        incoming.status = status

        self.session.add(incoming)
        self.session.flush()
        return incoming
