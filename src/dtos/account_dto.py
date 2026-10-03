from typing import List

from models import Account, LedgerEntry


class AccountDTO:
    @staticmethod
    def obj_to_dict(account: Account) -> dict:
        """No banco o status é um número; na resposta, uma palavra. Quem faz a travessia é o DTO."""
        return {
            "account_id": str(account.id),
            "customer_id": str(account.customer_id),
            "branch": account.branch,
            "account_number": account.number,
            "status": account.status.enumerator,
            "status_reason": account.status_reason,
            "status_events": AccountDTO.status_events(account),
            "balance": account.balance,
            "held_balance": account.held_balance,
            "available_balance": account.available_balance,
            "microcredit_eligible": account.customer.microcredit_eligible,
            "created_at": account.created_at.isoformat(),
        }

    @staticmethod
    def status_events(account: Account) -> List[dict]:
        """O caminho da conta, do nascimento ao status atual, mais antigo primeiro.

        O primeiro item sempre tem `from_status` nulo (nascimento) e o
        último sempre termina no `status` atual.
        """
        events = []
        for event in account.status_events:
            from_status = None
            if event.from_status is not None:
                from_status = event.from_status.enumerator

            events.append(
                {
                    "from_status": from_status,
                    "to_status": event.to_status.enumerator,
                    "reason": event.reason,
                    "created_at": event.created_at.isoformat(),
                }
            )
        return events

    @staticmethod
    def statement_item(entry: LedgerEntry) -> dict:
        return {
            "entry_id": entry.id,
            "type": entry.type,
            "method": entry.method,
            "amount": entry.amount,
            "balance_after": entry.balance_after,
            "reference_type": entry.reference_type,
            "reference_id": str(entry.reference_id) if entry.reference_id is not None else None,
            "external_id": entry.external_id,
            "created_at": entry.created_at.isoformat(),
        }

    @staticmethod
    def statement_items(entries: List[LedgerEntry]) -> List[dict]:
        items = []
        for entry in entries:
            items.append(AccountDTO.statement_item(entry))
        return items