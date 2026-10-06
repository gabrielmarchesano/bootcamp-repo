from sqlalchemy import Column, SmallInteger, String
 
from models.base import Base
 
 
class KycStatus(Base):
    """Resultado do KYC/PLD do cliente.
 
    A lista mora no banco (tabela kyc_status): estado que não está lá o banco
    recusa, sem precisar de if. As constantes abaixo são só os NOMES, para
    o código não espalhar texto solto; o id nunca aparece no Python."""
 
    __tablename__ = "kyc_status"
 
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
 
    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
 