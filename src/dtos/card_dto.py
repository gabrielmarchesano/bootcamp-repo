from typing import List

from models import Card, CardAuthorization, CreditWallet, Invoice


def _status_events(entity) -> List[dict]:
    """O caminho do status, mais antigo primeiro (a QI expõe `status_events` no cartão)."""
    events = []
    for event in entity.status_events:
        events.append(
            {
                "from_status": event.from_status.enumerator if event.from_status is not None else None,
                "to_status": event.to_status.enumerator,
                "reason": event.reason,
                "created_at": event.created_at.isoformat(),
            }
        )
    return events


class CardDTO:
    @staticmethod
    def wallet_to_dict(wallet: CreditWallet) -> dict:
        return {
            "wallet_id": str(wallet.id),
            "account_id": str(wallet.account_id),
            "status": wallet.status.enumerator,
            "status_events": _status_events(wallet),
            "total_limit": wallet.total_limit,
            "used_limit": wallet.used_limit,
            "available_limit": wallet.available_limit,
            "closing_day": wallet.closing_day,
            "due_day": wallet.due_day,
            "monthly_interest_rate": float(wallet.monthly_interest_rate),
            "fine_rate": float(wallet.fine_rate),
            "autopay": wallet.autopay,
            "created_at": wallet.created_at.isoformat(),
        }

    @staticmethod
    def card_to_dict(card: Card) -> dict:
        return {
            "card_id": str(card.id),
            "account_id": str(card.account_id),
            "wallet_id": str(card.wallet_id) if card.wallet_id is not None else None,
            "type": card.type,
            "functions": card.functions,
            "brand": card.brand,
            "last4": card.last4,
            "card_name": card.card_name,
            "printed_name": card.printed_name,
            "contactless_enabled": card.contactless_enabled,
            "status": card.status.enumerator,
            "status_events": _status_events(card),
            "created_at": card.created_at.isoformat(),
        }

    @staticmethod
    def authorization_to_dict(authorization: CardAuthorization) -> dict:
        return {
            "authorization_id": authorization.authorization_id,
            "card_id": str(authorization.card_id),
            "function": authorization.function,
            "status": authorization.status.enumerator,
            "response_code": authorization.response_code,
            "approval_code": authorization.approval_code,
            "denial_reason": authorization.denial_reason,
            "amount": authorization.amount,
            "authorized_amount": authorization.authorized_amount,
            "captured_amount": authorization.captured_amount,
            "refunded_amount": authorization.refunded_amount,
            "installment_count": authorization.installment_count,
            "events": [
                {"type": event.type, "amount": event.amount, "external_id": event.external_id}
                for event in authorization.events
            ],
        }

    @staticmethod
    def invoice_to_dict(invoice: Invoice, with_items: bool = False) -> dict:
        body = {
            "invoice_id": str(invoice.id),
            "wallet_id": str(invoice.wallet_id),
            "reference_month": invoice.reference_month.isoformat(),
            "status": invoice.status.enumerator,
            "closing_date": invoice.closing_date.isoformat(),
            "due_date": invoice.due_date.isoformat(),
            "total_amount": invoice.total_amount,
            "paid_amount": invoice.paid_amount,
        }
        if with_items:
            body["items"] = [
                {
                    "invoice_item_id": str(item.id),
                    "type": item.type,
                    "amount": item.amount,
                    "installment_number": item.installment_number,
                    "installment_total": item.installment_total,
                    "description": item.description,
                }
                for item in invoice.items
            ]
        return body