from sqlalchemy import BigInteger, Column, Date, String, func

from models.base import Base


class Fee(Base):
    __tablename__ = "fee"

    method = Column(String, primary_key=True)
    customer_segment = Column(String, primary_key=True)
    effective_from = Column(Date, primary_key=True, server_default=func.current_date())
    amount = Column(BigInteger, nullable=False)
