from typing import List

from models import Account, LedgerEntry


class AccountDTO:
    @staticmethod
    def obj_to_dict(account: Account) -> dict:
        return {
            "account_id": str(account.id),
            "customer_id": str(account.customer_id),
            "branch": account.branch,
            "account_number": account.number,
            "status": account.status,
            "status_reason": account.status_reason,
            "balance": account.balance,
            "held_balance": account.held_balance,
            "available_balance": account.available_balance,
            "microcredit_eligible": account.customer.microcredit_eligible,
            "created_at": account.created_at.isoformat(),
        }

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
