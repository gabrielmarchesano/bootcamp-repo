from sqlalchemy import CHAR, BigInteger, Column, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base


class IncomingTransfer(Base):
    __tablename__ = "incoming_transfer"

    SPI = "SPI"
    STR = "STR"

    CREDITED = "CREDITED"
    RETURNED = "RETURNED"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    rail = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    destination_account_id = Column(UUID(as_uuid=True), ForeignKey("account.id"))
    amount = Column(BigInteger, nullable=False)
    sender_name = Column(String)
    sender_document = Column(String)
    sender_ispb = Column(CHAR(8))
    status = Column(String, nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("rail", "external_id"),)
