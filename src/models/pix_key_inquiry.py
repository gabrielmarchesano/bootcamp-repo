from uuid import uuid4

from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey, func, Identity, String
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base


class PixKeyInquiry(Base):
    """Uma consulta ao DICT (QI: GET /pix_key/{key}).

    Devolve o `end_to_end_id` que o Pix por chave tem de usar. O banco
    garante as duas regras da QI: o e2e só vale para a conta que consultou
    (FK composta em transfer) e só vale uma vez (UNIQUE em transfer).
    Append-only: ninguém edita uma consulta.
    """

    __tablename__ = "pix_key_inquiry"

    # Tipo de conta e de pessoa no vocabulário da QI (account_type, owner_person_type)
    CHECKING = "CHECKING"
    NATURAL = "NATURAL"
    LEGAL = "LEGAL"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    key = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)
    account_id = Column(BigInteger, ForeignKey("account.id"), nullable=False)
    pix_key = Column(String(77), nullable=False)
    key_type = Column(String, nullable=False)
    end_to_end_id = Column(CHAR(32), nullable=False, unique=True)
    ispb = Column(CHAR(8), nullable=False)
    account_branch = Column(String(4), nullable=False)
    account_number = Column(String(20), nullable=False)
    account_digit = Column(CHAR(1))
    account_type = Column(String, nullable=False)
    owner_name = Column(String(120), nullable=False)
    owner_masked_document = Column(String(18), nullable=False)
    owner_person_type = Column(String, nullable=False)
    destination_account_id = Column(BigInteger, ForeignKey("account.id"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)