from models import CreditLine, Customer, Installment, Loan, LoanPayment


def _iso(value):
    return value.isoformat() if value is not None else None


def _rate(value) -> float:
    return float(value) if value is not None else None


def _exposure_key(customer: Customer) -> str:
    """O patrimônio é o dono (EI/MEI) ou o próprio titular."""
    root = customer.owner if customer.owner_customer_id is not None else customer
    return str(root.key)


class LoanDTO:
    @staticmethod
    def credit_line_to_dict(line: CreditLine, root: Customer, microcredit_balance: int) -> dict:
        return {
            "credit_line_id": str(line.key),
            "customer_id": str(root.key),
            "version": line.version,
            "total_limit": line.total_limit,
            "available_limit": line.available_limit,
            "microcredit_balance": microcredit_balance,
            "monthly_interest_rate": _rate(line.monthly_interest_rate),
            "origination_fee_rate": _rate(line.origination_fee_rate),
            "updated_at": _iso(line.updated_at),
        }

    @staticmethod
    def simulation_to_dict(terms) -> dict:
        return {
            "amount": terms.principal_amount,
            "installment_count": terms.installment_count,
            "term_days": terms.term_days,
            "monthly_interest_rate": _rate(terms.monthly_interest_rate),
            "effective_fee_rate": _rate(terms.effective_fee_rate),
            "origination_fee_amount": terms.origination_fee_amount,
            "net_amount": terms.net_amount,
            "effective_cost_monthly": _rate(terms.effective_cost_monthly),
            "effective_cost_annual": _rate(terms.effective_cost_annual),
            "installments": [
                {
                    "number": item.number,
                    "due_date": item.due_date.isoformat(),
                    "principal_amount": item.principal_amount,
                    "interest_amount": item.interest_amount,
                    "total_amount": item.total_amount,
                }
                for item in terms.installments
            ],
        }

    @staticmethod
    def installment_to_dict(installment: Installment) -> dict:
        return {
            "installment_id": str(installment.key),
            "number": installment.number,
            "due_date": installment.due_date.isoformat(),
            "principal_amount": installment.principal_amount,
            "interest_amount": installment.interest_amount,
            "total_amount": installment.total_amount,
            "paid_amount": installment.paid_amount,
            "remaining_amount": installment.remaining_amount,
            "status": installment.status.enumerator,
            "days_overdue": installment.days_overdue,
            "paid_at": _iso(installment.paid_at),
        }

    @staticmethod
    def loan_to_dict(loan: Loan, with_installments: bool = True) -> dict:
        body = {
            "loan_id": str(loan.key),
            "account_id": str(loan.account.key),
            "customer_id": str(loan.customer.key),
            "exposure_customer_id": _exposure_key(loan.customer),
            "credit_line_id": str(loan.credit_line.key),
            "credit_line_version": loan.credit_line_version,
            "status": loan.status.enumerator,
            "principal_amount": loan.principal_amount,
            "installment_count": loan.installment_count,
            "term_days": loan.term_days,
            "monthly_interest_rate": _rate(loan.monthly_interest_rate),
            "effective_fee_rate": _rate(loan.effective_fee_rate),
            "origination_fee_amount": loan.origination_fee_amount,
            "net_amount": loan.net_amount,
            "effective_cost_monthly": _rate(loan.effective_cost_monthly),
            "effective_cost_annual": _rate(loan.effective_cost_annual),
            "purpose": loan.purpose,
            "sfn_debt_declaration": loan.sfn_debt_declaration,
            "outstanding_principal": loan.outstanding_principal,
            "contracted_at": _iso(loan.contracted_at),
            "paid_off_at": _iso(loan.paid_off_at),
        }
        if with_installments:
            body["installments"] = [LoanDTO.installment_to_dict(item) for item in loan.installments]
        return body

    @staticmethod
    def payment_to_dict(payment: LoanPayment, loan: Loan) -> dict:
        return {
            "payment_id": str(payment.key),
            "loan_id": str(loan.key),
            "source": payment.source,
            "mode": payment.mode,
            "amount": payment.amount,
            "created_at": _iso(payment.created_at),
            "allocations": [
                {
                    "installment_id": str(allocation.installment.key),
                    "number": allocation.installment.number,
                    "principal_amount": allocation.principal_amount,
                    "interest_amount": allocation.interest_amount,
                    "prepayment_discount": allocation.prepayment_discount,
                }
                for allocation in sorted(payment.allocations, key=lambda item: item.installment.number)
            ],
            "loan": LoanDTO.loan_to_dict(loan),
        }
