from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, func
from sqlalchemy.orm import relationship

from models.base import Base


class CustomerRelationship(Base):
    """Quem opera a conta PJ além do titular: sócios e administradores de
    sociedade, procuradores de qualquer PJ. Liga PJ (LEGAL) → PF (NATURAL).

    A PK é composta pelas três colunas (legal, natural, role): a mesma PF
    pode ser, por exemplo, PARTNER e ADMINISTRATOR da mesma PJ. As FKs
    compostas garantem que o lado legal é sempre LEGAL e o natural sempre
    NATURAL (ux_customer_person_type é o alvo delas no v7).
    """

    __tablename__ = "customer_relationship"

    # Papéis (tipo enum_relationship_role no banco)
    PARTNER = "PARTNER"
    ADMINISTRATOR = "ADMINISTRATOR"
    ATTORNEY = "ATTORNEY"

    legal_customer_id = Column(BigInteger, ForeignKey("customer.id"), primary_key=True)
    legal_person_type = Column(String, nullable=False, server_default="LEGAL")
    natural_customer_id = Column(BigInteger, ForeignKey("customer.id"), primary_key=True)
    natural_person_type = Column(String, nullable=False, server_default="NATURAL")
    role = Column(String, primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    legal_customer = relationship("Customer", foreign_keys=[legal_customer_id], lazy="selectin")
    natural_customer = relationship("Customer", foreign_keys=[natural_customer_id], lazy="selectin")
