from models import Customer


class CustomerDTO:
    @staticmethod
    def obj_to_dict(customer: Customer) -> dict:
        account = customer.account

        return {
            "customer_id": str(customer.id),
            "cpf": customer.cpf,
            "name": customer.name,
            "birth_date": customer.birth_date.isoformat(),
            "type": customer.type,
            "cnpj": customer.cnpj,
            "annual_revenue": customer.annual_revenue,
            "revenue_reference_date": customer.revenue_reference_date.isoformat(),
            "microcredit_eligible": customer.microcredit_eligible,
            "kyc_status": customer.kyc_status.enumerator,
            "is_pep": customer.is_pep,
            "account_id": str(account.id) if account is not None else None,
            "created_at": customer.created_at.isoformat(),
        }

    @staticmethod
    def creation_to_dict(customer: Customer) -> dict:
        """A resposta do POST: o que a IF precisa para seguir o fluxo.

        `branch` e `account_number` vão além do contrato v6 de propósito: são
        o endereço que o SPI usa para creditar um PIX recebido nesta conta.
        """
        account = customer.account

        return {
            "customer_id": str(customer.id),
            "account_id": str(account.id),
            "branch": account.branch,
            "account_number": account.number,
            "status": account.status.enumerator,
            "status_reason": account.status_reason,
            "microcredit_eligible": customer.microcredit_eligible,
        }