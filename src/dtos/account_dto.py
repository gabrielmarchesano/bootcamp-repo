from typing import Dict, List, Optional, Tuple

from models import Account, LedgerEntry


class AccountDTO:
    @staticmethod
    def obj_to_dict(account: Account) -> dict:
        """No banco o status é um número; na resposta, uma palavra. Quem faz a travessia é o DTO."""
        return {
            "account_id": str(account.key),
            "customer_id": str(account.customer.key),
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
    def statement_item(entry: LedgerEntry, reference_keys: Dict[Tuple[str, int], str]) -> dict:
        """`reference_id` sai como o identificador público da referência
        (key UUID, ou o authorization_id da rede no cartão)."""
        reference_id: Optional[str] = None
        if entry.reference_id is not None:
            reference_id = reference_keys.get((entry.reference_type, entry.reference_id))

        return {
            "entry_id": entry.id,
            "type": entry.type,
            "method": entry.method,
            "amount": entry.amount,
            "balance_after": entry.balance_after,
            "reference_type": entry.reference_type,
            "reference_id": reference_id,
            "external_id": entry.external_id,
            "created_at": entry.created_at.isoformat(),
        }

    @staticmethod
    def statement_items(entries: List[LedgerEntry], reference_keys: Dict[Tuple[str, int], str]) -> List[dict]:
        return [AccountDTO.statement_item(entry, reference_keys) for entry in entries]
