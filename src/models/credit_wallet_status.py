from sqlalchemy import Column, SmallInteger, String

from models.base import Base


class CreditWalletStatus(Base):
    """Status da carteira de crédito (QI: wallet).

    A lista mora no banco (tabela credit_wallet_status): estado que não está lá o banco
    recusa, sem precisar de if. As constantes abaixo são só os NOMES, para
    o código não espalhar texto solto; o id nunca aparece no Python."""

    __tablename__ = "credit_wallet_status"

    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"

    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
