from sqlalchemy import Column, SmallInteger, String

from models.base import Base


class CardStatus(Base):
    """Status do cartão, no ciclo de vida da QI (inicial, ativo, bloqueio temporário, terminal).

    A lista mora no banco (tabela card_status): estado que não está lá o banco
    recusa, sem precisar de if. As constantes abaixo são só os NOMES, para
    o código não espalhar texto solto; o id nunca aparece no Python."""

    __tablename__ = "card_status"

    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    CANCELED = "CANCELED"
    EMBOSSING = "EMBOSSING"
    LOST = "LOST"
    STOLEN = "STOLEN"
    FRAUD = "FRAUD"

    # Terminais: não voltam. Cartão perdido não é "desbloqueado" — é reemitido.
    TERMINAL = (CANCELED, LOST, STOLEN, FRAUD)

    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
