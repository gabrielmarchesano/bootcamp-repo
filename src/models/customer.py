from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Identity, String, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.schema import FetchedValue

from models.base import Base
from models.types import PgEnum
from models.kyc_status import KycStatus


class Customer(Base):
    __tablename__ = "customer"

    # Natureza da pessoa (vocabulário do DICT): tipo enum_person_type no banco.
    NATURAL = "NATURAL"
    LEGAL = "LEGAL"

    # Naturezas jurídicas (só LEGAL). EI inclui o MEI (MEI é EI no SIMEI).
    EI = "EI"
    SLU = "SLU"
    LTDA = "LTDA"

    # Segmento de tarifa (coluna gerada fee_segment)
    INDIVIDUAL = "INDIVIDUAL"
    BUSINESS = "BUSINESS"

    # id: PK interna (alvo das FKs, nunca sai do banco).
    # key: identificador público — é o que a API recebe e devolve.
    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    person_type = Column(PgEnum("enum_person_type"), nullable=False)
    document = Column(String(14), nullable=False, unique=True)  # CPF (11) ou CNPJ (14), só dígitos
    name = Column(String, nullable=False)
    birth_date = Column(Date)  # só NATURAL
    legal_nature = Column(PgEnum("enum_legal_nature"))  # só LEGAL
    # Só EI: a pessoa natural que É este CNPJ (patrimônio único com a PF).
    owner_customer_id = Column(BigInteger, ForeignKey("customer.id"))
    owner_person_type = Column(PgEnum("enum_person_type"))
    # Colunas GERADAS pelo banco (GENERATED ALWAYS ... STORED). O código
    # NUNCA grava nelas: FetchedValue() diz ao SQLAlchemy que o valor vem
    # do banco e precisa de refresh depois do INSERT para ser lido.
    exposure_customer_id = Column(BigInteger, server_default=FetchedValue())
    fee_segment = Column(PgEnum("enum_customer_segment"), server_default=FetchedValue())  # INDIVIDUAL / BUSINESS
    annual_revenue = Column(BigInteger, nullable=False)
    revenue_reference_date = Column(Date, nullable=False, server_default=func.current_date())
    microcredit_eligible = Column(Boolean, server_default=FetchedValue())  # annual_revenue <= 36000000
    kyc_status_id = Column(SmallInteger, ForeignKey(KycStatus.id), nullable=False)
    is_pep = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    kyc_status = relationship("KycStatus", foreign_keys=[kyc_status_id], lazy="selectin")
    # O dono do EI/MEI (a PF). Só leitura pela relação: quem grava é owner_customer_id.
    owner = relationship("Customer", remote_side=[id], foreign_keys=[owner_customer_id], lazy="select")
    # No v7 um titular tem N contas (customer_id deixou de ser UNIQUE), então
    # o relationship é uma LISTA. Quem precisa de "a conta" escolhe de forma
    # determinística (ex. a mais antiga por created_at).
    accounts = relationship(
        "Account",
        back_populates="customer",
        order_by="Account.created_at",
        lazy="selectin",
    )
