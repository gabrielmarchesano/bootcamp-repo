from sqlalchemy import Column, SmallInteger, String
 
from models.base import Base
 
 
class TransferStatus(Base):
    """Status da transferência de saída.
 
    A lista mora no banco (tabela transfer_status): estado que não está lá o banco
    recusa, sem precisar de if. As constantes abaixo são só os NOMES, para
    o código não espalhar texto solto; o id nunca aparece no Python."""
 
    __tablename__ = "transfer_status"
 
    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"
    FAILED = "FAILED"
 
    # Status que contam para o limite noturno: o dinheiro já saiu ou vai sair
    OUTFLOW = (CREATED, SENT, COMPLETED)
 
    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
 