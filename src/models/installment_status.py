from sqlalchemy import Column, SmallInteger, String

from models.base import Base


class InstallmentStatus(Base):
    """Status da parcela (tabela installment_status)."""

    __tablename__ = "installment_status"

    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    OVERDUE = "OVERDUE"
    PAID = "PAID"

    # Em aberto: o que a cobrança e o pagamento ainda podem abater.
    UNPAID = (OPEN, PARTIAL, OVERDUE)

    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
