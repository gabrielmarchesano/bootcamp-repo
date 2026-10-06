from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Numeric, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.credit_wallet_status import CreditWalletStatus


class CreditWallet(Base):
    """Carteira de crédito (QI: wallet). "Uma carteira = uma fatura".

    Limite, ciclo e encargos moram aqui, não no cartão: o virtual, o físico
    e a reemissão consomem o MESMO limite e caem na MESMA fatura.
    """

    __tablename__ = "credit_wallet"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    account_id = Column(UUID(as_uuid=True), ForeignKey("account.id"), nullable=False)
    status_id = Column(SmallInteger, ForeignKey(CreditWalletStatus.id), nullable=False)
    total_limit = Column(BigInteger, nullable=False)
    used_limit = Column(BigInteger, nullable=False)
    closing_day = Column(SmallInteger, nullable=False)
    due_day = Column(SmallInteger, nullable=False)
    monthly_interest_rate = Column(Numeric(7, 6), nullable=False)
    fine_rate = Column(Numeric(5, 4), nullable=False)
    autopay = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    status = relationship("CreditWalletStatus", foreign_keys=[status_id], lazy="selectin")
    status_events = relationship(
        "CreditWalletStatusEvent", back_populates="credit_wallet", order_by="CreditWalletStatusEvent.id", lazy="select"
    )

    @property
    def available_limit(self) -> int:
        return max(self.total_limit - self.used_limit, 0)