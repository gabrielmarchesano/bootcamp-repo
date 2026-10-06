from typing import List

from models import IncomingTransfer, Transfer


def _iso(value):
    return value.isoformat() if value is not None else None


class TransferDTO:
    @staticmethod
    def obj_to_dict(transfer: Transfer) -> dict:
        """A transferência como a IF enxerga.

        `request_control_key` é o Idempotency-Key ecoado de volta, como a QI
        faz. O `request_hash` continua de fora: é detalhe da deduplicação.
        """
        if transfer.on_us and transfer.destination_account_id is not None:
            destination = {"account_id": str(transfer.destination_account_id)}
        elif transfer.destination_ispb is not None:
            destination = {
                "ispb": transfer.destination_ispb,
                "branch": transfer.destination_branch,
                "number": transfer.destination_account,
                "digit": transfer.destination_account_digit,
                "account_type": transfer.destination_account_type,
                "document": transfer.destination_document,
                "name": transfer.destination_name,
            }
        else:
            destination = None

        body = {
            "transfer_id": str(transfer.id),
            "request_control_key": transfer.idempotency_key,
            "method": transfer.method,
            "status": transfer.status.enumerator,
            "amount": transfer.amount,
            "fee": transfer.fee,
            "source_account_id": str(transfer.source_account_id),
            "on_us": transfer.on_us,
            "destination": destination,
            "created_at": transfer.created_at.isoformat(),
            "completed_at": _iso(transfer.completed_at),
        }

        if transfer.method == Transfer.PIX:
            body["pix"] = {
                "pix_transfer_type": transfer.pix_transfer_type,
                "pix_key": transfer.pix_key,
                "end_to_end_id": transfer.end_to_end_id,
                "pix_message": transfer.pix_message,
                "original_incoming_transfer_id": _iso_id(transfer.original_incoming_transfer_id),
                "reversal_reason": transfer.reversal_reason,
            }

        if transfer.method == Transfer.TED:
            body["ted"] = {
                "str_control_number": transfer.str_control_number,
                "scheduled_for": _iso(transfer.scheduled_for),
            }

        if transfer.failure_code is not None or transfer.failure_reason is not None:
            body["failure"] = {"code": transfer.failure_code, "reason": transfer.failure_reason}

        return body

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
            "pix_transfer_type": incoming.pix_transfer_type,
            "external_id": incoming.external_id,
            "status": incoming.status.enumerator,
            "amount": incoming.amount,
            "original_transfer_id": _iso_id(incoming.original_transfer_id),
        }


def _iso_id(value):
    return str(value) if value is not None else None