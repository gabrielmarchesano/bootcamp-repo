from sqlalchemy import Column, SmallInteger, String

from models.base import Base


class OutboxEventStatus(Base):
    """Status de envio do evento para a IF (técnico: não tem eventos).

    A lista mora no banco (tabela outbox_event_status): estado que não está lá o banco
    recusa, sem precisar de if. As constantes abaixo são só os NOMES, para
    o código não espalhar texto solto; o id nunca aparece no Python."""

    __tablename__ = "outbox_event_status"

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"

    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
