from datetime import date  # noqa: F401 (tipo do birth_date)
from uuid import UUID

from sqlalchemy import func

from database import Context
from models import Customer


class CustomerRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(self, customer_data: dict, birth_date: date, kyc_status: str, microcredit_eligible: bool) -> Customer:
        customer = Customer()
        customer.cpf = customer_data["cpf"]
        customer.name = customer_data["name"]
        customer.birth_date = birth_date
        customer.type = customer_data["type"]
        customer.cnpj = customer_data.get("cnpj")
        customer.annual_revenue = customer_data["annual_revenue"]
        customer.microcredit_eligible = microcredit_eligible
        customer.kyc_status = kyc_status
        customer.is_pep = customer_data.get("is_pep", False)

        self.session.add(customer)
        return customer

    def get_by_id(self, customer_id: UUID) -> Customer:
        return self.session.query(Customer).filter(Customer.id == customer_id).first()

    def get_by_cpf(self, cpf: str) -> Customer:
        return self.session.query(Customer).filter(Customer.cpf == cpf).first()

    def get_by_cnpj(self, cnpj: str) -> Customer:
        return self.session.query(Customer).filter(Customer.cnpj == cnpj).first()

    def update_revenue(self, customer: Customer, annual_revenue: int, microcredit_eligible: bool) -> None:
        customer.annual_revenue = annual_revenue
        customer.microcredit_eligible = microcredit_eligible
        customer.revenue_reference_date = func.current_date()
        customer.updated_at = func.now()
