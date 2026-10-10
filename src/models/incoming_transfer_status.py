from sqlalchemy import Column, SmallInteger, String

from models.base import Base


class IncomingTransferStatus(Base):
    """Desfecho de uma entrada via SPI/STR. Nasce final: não tem eventos.

    A lista mora no banco (tabela incoming_transfer_status): estado que não está lá o banco
    recusa, sem precisar de if. As constantes abaixo são só os NOMES, para
    o código não espalhar texto solto; o id nunca aparece no Python."""

    __tablename__ = "incoming_transfer_status"

    CREDITED = "CREDITED"
    RETURNED = "RETURNED"

    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
