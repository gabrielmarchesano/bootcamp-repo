from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, String, func
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base


class LedgerEntry(Base):
    """Uma perna de um lançamento em partidas dobradas.

    Não tem método de atualizar nem de apagar — e nem adiantaria: o banco
    recusa UPDATE e DELETE nesta tabela (trigger tg_immutable_ledger).
    Corrigir um lançamento é lançar o estorno.
    """

    __tablename__ = "ledger_entry"

    # Tipos de lançamento usados até aqui (a lista completa está no CHECK do database.sql)
    TEF_SENT = "TEF_SENT"
    TEF_RECEIVED = "TEF_RECEIVED"
    PIX_RECEIVED = "PIX_RECEIVED"
    TRANSFER_FEE = "TRANSFER_FEE"

    # Referências
    REF_TRANSFER = "TRANSFER"
    REF_INCOMING_TRANSFER = "INCOMING_TRANSFER"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    operation_id = Column(UUID(as_uuid=True), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("account.id"), nullable=False)
    amount = Column(BigInteger, nullable=False)
    type = Column(String, nullable=False)
    method = Column(String)
    balance_after = Column(BigInteger)
    reference_type = Column(String)
    reference_id = Column(UUID(as_uuid=True))
    external_id = Column(String)
    reversal_of_id = Column(BigInteger, ForeignKey("ledger_entry.id"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
