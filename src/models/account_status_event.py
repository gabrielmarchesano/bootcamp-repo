from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, func, Identity, SmallInteger, String
from sqlalchemy.orm import relationship

from models.base import Base
from models.account_status import AccountStatus


class AccountStatusEvent(Base):
    """Uma linha por mudança de status da conta: de onde, para onde, quando e por quê.

    A coluna `account.status_id` responde ONDE está agora; esta tabela
    responde desde quando e por qual caminho. Append-only no banco
    (trigger): ninguém edita nem apaga um evento.

    Não crie evento à mão: quem grava é o repository, no mesmo método
    que muda o status. Assim não existe mudança de status sem rastro.
    """

    __tablename__ = "account_status_event"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    account_id = Column(BigInteger, ForeignKey("account.id"), nullable=False)
    from_status_id = Column(SmallInteger, ForeignKey(AccountStatus.id))  # nulo ao nascer
    to_status_id = Column(SmallInteger, ForeignKey(AccountStatus.id), nullable=False)
    reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    account = relationship("Account", back_populates="status_events")
    from_status = relationship("AccountStatus", foreign_keys=[from_status_id], lazy="selectin")
    to_status = relationship("AccountStatus", foreign_keys=[to_status_id], lazy="selectin")
