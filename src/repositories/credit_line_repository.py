from typing import Optional

from sqlalchemy import func, text

from database import Context
from models import CreditLine, CreditLineVersion


class CreditLineRepository:
    """Linha de microcrédito do patrimônio.

    Na ordem global de lock vem logo depois da conta:
    account → credit_line → loan → installment.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_customer(self, exposure_customer_id: int) -> Optional[CreditLine]:
        return self.session.query(CreditLine).filter(CreditLine.customer_id == exposure_customer_id).first()

    def lock_by_customer(self, exposure_customer_id: int) -> Optional[CreditLine]:
        return (
            self.session.query(CreditLine)
            .filter(CreditLine.customer_id == exposure_customer_id)
            .populate_existing()
            .with_for_update()
            .first()
        )

    def lock(self, credit_line_id: int) -> Optional[CreditLine]:
        return (
            self.session.query(CreditLine)
            .filter(CreditLine.id == credit_line_id)
            .populate_existing()
            .with_for_update()
            .first()
        )

    def microcredit_balance(self, exposure_customer_id: int) -> int:
        """Saldo de microcrédito do patrimônio (principal em aberto dos contratos ativos).

        Lê a view vw_microcredit_balance: soma a PF, o EI/MEI dela e todas as
        contas de cada um. Premissa D1 da RFC: o teto conta o principal.
        """
        # SUM de BIGINT volta NUMERIC (Decimal): vira int para não vazar no JSON do outbox.
        balance = self.session.execute(
            text(
                "SELECT COALESCE(microcredit_balance, 0) FROM vw_microcredit_balance "
                "WHERE exposure_customer_id = :customer_id"
            ),
            {"customer_id": exposure_customer_id},
        ).scalar()
        return int(balance or 0)

    def create(self, exposure_customer_id: int, data: dict, available_limit: int) -> CreditLine:
        line = CreditLine()
        line.customer_id = exposure_customer_id
        line.version = 1
        line.total_limit = data["total_limit"]
        line.available_limit = available_limit
        line.monthly_interest_rate = data["monthly_interest_rate"]
        line.origination_fee_rate = data["origination_fee_rate"]
        self.session.add(line)
        self.session.flush()
        self._add_version(line)
        return line

    def update(self, line: CreditLine, data: dict, available_limit: int) -> None:
        """Nova versão da linha. Contratos antigos seguem apontando para a versão deles."""
        line.version = line.version + 1
        line.total_limit = data["total_limit"]
        line.available_limit = available_limit
        line.monthly_interest_rate = data["monthly_interest_rate"]
        line.origination_fee_rate = data["origination_fee_rate"]
        line.updated_at = func.now()
        self._add_version(line)

    def _add_version(self, line: CreditLine) -> None:
        version = CreditLineVersion()
        version.credit_line_id = line.id
        version.version = line.version
        version.total_limit = line.total_limit
        version.monthly_interest_rate = line.monthly_interest_rate
        version.origination_fee_rate = line.origination_fee_rate
        self.session.add(version)
        self.session.flush()
