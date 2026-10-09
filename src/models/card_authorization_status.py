from sqlalchemy import Column, SmallInteger, String

from models.base import Base


class CardAuthorizationStatus(Base):
    """Status da autorização. REFUNDED existe na lista, mas não é mais destino (estorno é evento).

    A lista mora no banco (tabela card_authorization_status): estado que não está lá o banco
    recusa, sem precisar de if. As constantes abaixo são só os NOMES, para
    o código não espalhar texto solto; o id nunca aparece no Python."""

    __tablename__ = "card_authorization_status"

    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CAPTURED = "CAPTURED"
    EXPIRED = "EXPIRED"
    REVERSED = "REVERSED"
    REFUNDED = "REFUNDED"

    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
