from sqlalchemy import Column, SmallInteger, String

from models.base import Base


class InvoiceStatus(Base):
    """Status da fatura. FUTURE recebe parcelas de meses seguintes.

    A lista mora no banco (tabela invoice_status): estado que não está lá o banco
    recusa, sem precisar de if. As constantes abaixo são só os NOMES, para
    o código não espalhar texto solto; o id nunca aparece no Python."""

    __tablename__ = "invoice_status"

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    FUTURE = "FUTURE"

    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)