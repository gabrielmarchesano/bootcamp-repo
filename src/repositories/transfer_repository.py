from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, text, tuple_

from database import Context
from models import Account, Fee, Transfer


class TransferRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_id(self, transfer_id: UUID) -> Transfer:
        return self.session.query(Transfer).filter(Transfer.id == transfer_id).first()

    def get_by_idempotency_key(self, idempotency_key: str) -> Transfer:
        return self.session.query(Transfer).filter(Transfer.idempotency_key == idempotency_key).first()

    def create_tef(
        self,
        idempotency_key: str,
        request_hash: str,
        source: Account,
        destination: Account,
        amount: int,
        fee: int,
    ) -> Transfer:
        transfer = Transfer()
        transfer.idempotency_key = idempotency_key
        transfer.request_hash = request_hash
        transfer.source_account_id = source.id
        transfer.destination_account_id = destination.id
        transfer.method = Transfer.TEF
        transfer.amount = amount
        transfer.fee = fee
        transfer.on_us = True
        # TEF é síncrona: nasce e morre na mesma transação.
        transfer.status = Transfer.COMPLETED
        transfer.completed_at = func.now()

        self.session.add(transfer)
        self.session.flush()
        return transfer

    def current_fee(self, method: str, customer_type: str) -> int:
        """A tarifa vigente hoje: a de `effective_from` mais recente que já começou."""
        fee = (
            self.session.query(Fee)
            .filter(
                Fee.method == method,
                Fee.customer_type == customer_type,
                Fee.effective_from <= func.current_date(),
            )
            .order_by(Fee.effective_from.desc())
            .first()
        )
        if fee is None:
            return 0
        return fee.amount

    def local_now(self) -> datetime:
        """A hora de Brasília, sem fuso, segundo o relógio do PRÓPRIO banco.

        Perguntar ao Postgres e não ao Python evita duas fontes de
        verdade para "que horas são" — e evita depender do pacote de fusos
        na imagem Docker.
        """
        return self.session.execute(text("SELECT now() AT TIME ZONE 'America/Sao_Paulo'")).scalar_one()

    def outflow_since(self, account_id: UUID, local_window_start: datetime) -> int:
        """Soma das saídas da conta desde o início da janela noturna (hora local)."""
        return self.session.execute(
            text(
                "SELECT COALESCE(SUM(amount), 0) FROM transfer "
                "WHERE source_account_id = :account_id "
                "AND status = ANY(:statuses) "
                "AND created_at >= (CAST(:window_start AS timestamp) AT TIME ZONE 'America/Sao_Paulo')"
            ),
            {
                "account_id": account_id,
                "statuses": list(Transfer.OUTFLOW_STATUSES),
                "window_start": local_window_start,
            },
        ).scalar_one()

    def list_by_account(
        self, account_id: UUID, statuses: List[str], limit: int, after: Optional[Tuple[datetime, str]]
    ) -> List[Transfer]:
        """Transferências em que a conta é origem OU destino, mais novas primeiro."""
        query = self.session.query(Transfer).filter(
            (Transfer.source_account_id == account_id) | (Transfer.destination_account_id == account_id)
        )

        if statuses:
            query = query.filter(Transfer.status.in_(statuses))

        if after is not None:
            after_created_at, after_id = after
            query = query.filter(tuple_(Transfer.created_at, Transfer.id) < tuple_(after_created_at, UUID(after_id)))

        query = query.order_by(Transfer.created_at.desc(), Transfer.id.desc())

        return query.limit(limit + 1).all()
