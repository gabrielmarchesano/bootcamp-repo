from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, text, tuple_

from database import Context
from models import Account, Fee, Transfer, TransferStatus, TransferStatusEvent
from repositories.enumerator_repository import EnumeratorRepository


class TransferRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

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
        # TEF é síncrona: nasce e morre na mesma transação, já COMPLETED.
        transfer.status = self.enumerators.get(TransferStatus, TransferStatus.COMPLETED)
        transfer.completed_at = func.now()

        self.session.add(transfer)
        self._record_status_event(transfer, None, transfer.status, None)

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
                "SELECT COALESCE(SUM(t.amount), 0) FROM transfer t "
                "JOIN transfer_status s ON s.id = t.status_id "
                "WHERE t.source_account_id = :account_id "
                "AND s.enumerator = ANY(:statuses) "
                "AND t.created_at >= (CAST(:window_start AS timestamp) AT TIME ZONE 'America/Sao_Paulo')"
            ),
            {
                "account_id": account_id,
                "statuses": list(TransferStatus.OUTFLOW),
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
            # O filtro chega com nomes ("COMPLETED"); a junção os traduz.
            query = query.join(Transfer.status).filter(TransferStatus.enumerator.in_(statuses))

        if after is not None:
            after_created_at, after_id = after
            query = query.filter(tuple_(Transfer.created_at, Transfer.id) < tuple_(after_created_at, UUID(after_id)))

        query = query.order_by(Transfer.created_at.desc(), Transfer.id.desc())

        return query.limit(limit + 1).all()

    def _record_status_event(
        self,
        transfer: Transfer,
        from_status: Optional[TransferStatus],
        to_status: TransferStatus,
        reason: Optional[str],
    ) -> None:
        """Mesmo desenho do AccountRepository: o evento vai pendurado na relação.

        Hoje só a TEF existe, e ela nasce final (null → COMPLETED). Quando
        PIX/TED de saída chegarem (CREATED → SENT → COMPLETED/RETURNED),
        cada transição passa por aqui.
        """
        event = TransferStatusEvent()
        event.transfer = transfer
        event.from_status = from_status
        event.to_status = to_status
        event.reason = reason

        self.session.add(event)