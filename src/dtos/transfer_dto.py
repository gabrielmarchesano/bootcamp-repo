from typing import List

from models import IncomingTransfer, Transfer


class TransferDTO:
    @staticmethod
    def obj_to_dict(transfer: Transfer) -> dict:
        """A transferência como a IF enxerga. Sem `idempotency_key` nem `request_hash`:
        são detalhes internos da deduplicação, não informação de negócio."""
        if transfer.method == Transfer.TEF:
            destination = {"account_id": str(transfer.destination_account_id)}
        else:
            destination = None

        completed_at = None
        if transfer.completed_at is not None:
            completed_at = transfer.completed_at.isoformat()

        return {
            "transfer_id": str(transfer.id),
            "method": transfer.method,
            "status": transfer.status,
            "amount": transfer.amount,
            "fee": transfer.fee,
            "source_account_id": str(transfer.source_account_id),
            "destination": destination,
            "created_at": transfer.created_at.isoformat(),
            "completed_at": completed_at,
        }

    @staticmethod
    def list_obj_to_list_dict(transfers: List[Transfer]) -> List[dict]:
        items = []
        for transfer in transfers:
            items.append(TransferDTO.obj_to_dict(transfer))
        return items

    @staticmethod
    def incoming_to_dict(incoming: IncomingTransfer) -> dict:
        return {
            "incoming_transfer_id": str(incoming.id),
            "rail": incoming.rail,
            "external_id": incoming.external_id,
            "status": incoming.status,
            "amount": incoming.amount,
        }
