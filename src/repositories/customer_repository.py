from datetime import date  # noqa: F401 (tipo do birth_date)
from uuid import UUID

from sqlalchemy import func

from database import Context
from models import Customer, CustomerRelationship, KycStatus
from repositories.enumerator_repository import EnumeratorRepository


class CustomerRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

    def create(self, customer_data: dict, birth_date, kyc_status: str) -> Customer:
        """Grava as colunas que o cliente informa. As colunas GERADAS
        (exposure_customer_id, fee_segment, microcredit_eligible) NÃO são
        tocadas — o banco as calcula, e o controller faz refresh para lê-las.
        """
        customer = Customer()
        customer.person_type = customer_data["person_type"]
        customer.document = customer_data["document"]
        customer.name = customer_data["name"]
        customer.birth_date = birth_date
        customer.legal_nature = customer_data.get("legal_nature")

        owner_customer_id = customer_data.get("owner_customer_id")
        if owner_customer_id is not None:
            customer.owner_customer_id = owner_customer_id
            customer.owner_person_type = Customer.NATURAL

        customer.annual_revenue = customer_data["annual_revenue"]
        customer.kyc_status = self.enumerators.get(KycStatus, kyc_status)
        customer.is_pep = customer_data.get("is_pep", False)

        self.session.add(customer)
        return customer

    def get_by_id(self, customer_id: UUID) -> Customer:
        return self.session.query(Customer).filter(Customer.id == customer_id).first()

    def get_by_document(self, document: str) -> Customer:
        return self.session.query(Customer).filter(Customer.document == document).first()

    def update_revenue(self, customer: Customer, annual_revenue: int) -> None:
        """Atualiza o faturamento. microcredit_eligible é coluna GERADA: o
        banco recalcula sozinho — não gravamos aqui."""
        customer.annual_revenue = annual_revenue
        customer.revenue_reference_date = func.current_date()
        customer.updated_at = func.now()

    def add_relationship(
        self, legal_customer_id: UUID, natural_customer_id: UUID, role: str
    ) -> CustomerRelationship:
        relationship = CustomerRelationship()
        relationship.legal_customer_id = legal_customer_id
        relationship.legal_person_type = Customer.LEGAL
        relationship.natural_customer_id = natural_customer_id
        relationship.natural_person_type = Customer.NATURAL
        relationship.role = role

        self.session.add(relationship)
        return relationship
