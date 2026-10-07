from models import Account, Customer, CustomerRelationship


class CustomerDTO:
    @staticmethod
    def _primary_account(customer: Customer):
        """A conta "principal" do titular: a mais antiga por created_at.

        No v7 um titular tem N contas; o relationship `accounts` já vem
        ordenado por created_at, então a primeira é a determinística.
        """
        accounts = customer.accounts
        if not accounts:
            return None
        return accounts[0]

    @staticmethod
    def obj_to_dict(customer: Customer) -> dict:
        account = CustomerDTO._primary_account(customer)

        return {
            "customer_id": str(customer.id),
            "person_type": customer.person_type,
            "document": customer.document,
            "name": customer.name,
            "birth_date": customer.birth_date.isoformat() if customer.birth_date is not None else None,
            "legal_nature": customer.legal_nature,
            "owner_customer_id": str(customer.owner_customer_id) if customer.owner_customer_id is not None else None,
            "annual_revenue": customer.annual_revenue,
            "revenue_reference_date": customer.revenue_reference_date.isoformat(),
            "microcredit_eligible": customer.microcredit_eligible,
            "kyc_status": customer.kyc_status.enumerator,
            "is_pep": customer.is_pep,
            "account_id": str(account.id) if account is not None else None,
            "created_at": customer.created_at.isoformat(),
        }

    @staticmethod
    def creation_to_dict(customer: Customer, account: Account) -> dict:
        """A resposta do POST: o que a IF precisa para seguir o fluxo.

        `branch` e `account_number` vão além do contrato v6 de propósito: são
        o endereço que o SPI usa para creditar um PIX recebido nesta conta.
        A conta da criação é a recém-aberta (não dependemos da ordenação).
        """
        return {
            "customer_id": str(customer.id),
            "account_id": str(account.id),
            "branch": account.branch,
            "account_number": account.number,
            "status": account.status.enumerator,
            "status_reason": account.status_reason,
            "microcredit_eligible": customer.microcredit_eligible,
        }

    @staticmethod
    def account_to_dict(account: Account) -> dict:
        return {
            "account_id": str(account.id),
            "customer_id": str(account.customer_id),
            "branch": account.branch,
            "account_number": account.number,
            "status": account.status.enumerator,
            "status_reason": account.status_reason,
            "created_at": account.created_at.isoformat(),
        }

    @staticmethod
    def accounts_to_dict(accounts) -> dict:
        return {"items": [CustomerDTO.account_to_dict(account) for account in accounts]}

    @staticmethod
    def relationship_to_dict(relationship: CustomerRelationship) -> dict:
        return {
            "legal_customer_id": str(relationship.legal_customer_id),
            "natural_customer_id": str(relationship.natural_customer_id),
            "role": relationship.role,
            "created_at": relationship.created_at.isoformat(),
        }
