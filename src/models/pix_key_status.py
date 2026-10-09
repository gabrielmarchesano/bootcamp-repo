from sqlalchemy import Column, SmallInteger, String

from models.base import Base


class PixKeyStatus(Base):
    """Status de uma chave Pix nossa.

    A lista mora no banco (tabela pix_key_status): estado que não está lá o banco
    recusa, sem precisar de if. As constantes abaixo são só os NOMES, para
    o código não espalhar texto solto; o id nunca aparece no Python."""

    __tablename__ = "pix_key_status"

    ACTIVE = "ACTIVE"
    DELETED = "DELETED"

    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
