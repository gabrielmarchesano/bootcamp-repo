from sqlalchemy import Column, SmallInteger, String

from models.base import Base


class AccountStatus(Base):
    """Status da conta.

    A lista mora no banco (tabela account_status): estado que não está lá o banco
    recusa, sem precisar de if. As constantes abaixo são só os NOMES, para
    o código não espalhar texto solto; o id nunca aparece no Python."""

    __tablename__ = "account_status"

    REQUESTED = "REQUESTED"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"

    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
