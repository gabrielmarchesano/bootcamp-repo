from sqlalchemy import BigInteger, Column, Date, func

from models.base import Base
from models.types import PgEnum


class Fee(Base):
    __tablename__ = "fee"

    method = Column(PgEnum("enum_transfer_method"), primary_key=True)
    customer_segment = Column(PgEnum("enum_customer_segment"), primary_key=True)
    effective_from = Column(Date, primary_key=True, server_default=func.current_date())
    amount = Column(BigInteger, nullable=False)
