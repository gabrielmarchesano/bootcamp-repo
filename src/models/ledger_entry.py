from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, func, Identity, String
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
    PIX_SENT = "PIX_SENT"
    PIX_RECEIVED = "PIX_RECEIVED"
    PIX_REVERSAL_SENT = "PIX_REVERSAL_SENT"
    PIX_REVERSAL_RECEIVED = "PIX_REVERSAL_RECEIVED"
    TED_SENT = "TED_SENT"
    TED_RECEIVED = "TED_RECEIVED"
    TRANSFER_FEE = "TRANSFER_FEE"
    DEBIT_PURCHASE = "DEBIT_PURCHASE"
    PURCHASE_REFUND = "PURCHASE_REFUND"
    REVERSAL = "REVERSAL"
    DISBURSEMENT = "DISBURSEMENT"
    ORIGINATION_FEE = "ORIGINATION_FEE"
    INSTALLMENT_PAYMENT = "INSTALLMENT_PAYMENT"
    INVOICE_PAYMENT = "INVOICE_PAYMENT"

    # Referências
    REF_TRANSFER = "TRANSFER"
    REF_INCOMING_TRANSFER = "INCOMING_TRANSFER"
    REF_CARD_AUTHORIZATION = "CARD_AUTHORIZATION"
    REF_LOAN = "LOAN"
    REF_LOAN_PAYMENT = "LOAN_PAYMENT"
    REF_INVOICE_PAYMENT = "INVOICE_PAYMENT"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    operation_id = Column(UUID(as_uuid=True), nullable=False)
    account_id = Column(BigInteger, ForeignKey("account.id"), nullable=False)
    amount = Column(BigInteger, nullable=False)
    type = Column(String, nullable=False)
    method = Column(String)
    balance_after = Column(BigInteger)
    reference_type = Column(String)
    reference_id = Column(BigInteger)  # id interno da entidade de referência
    external_id = Column(String)
    reversal_of_id = Column(BigInteger, ForeignKey("ledger_entry.id"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
