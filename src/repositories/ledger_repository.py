from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy import tuple_

from database import Context
from models import Account, LedgerEntry


class LedgerLeg:
    """Uma perna do lançamento, antes de virar linha no banco.

    `amount` positivo é crédito, negativo é débito. As pernas de uma
    operação precisam somar zero — se não somarem, o próprio banco recusa
    no COMMIT (trigger tg_double_entry).
    """

    def __init__(self, account: Account, amount: int, entry_type: str, method: str = None, external_id: str = None):
        self.account = account
        self.amount = amount
        self.entry_type = entry_type
        self.method = method
        self.external_id = external_id


class LedgerRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def post(self, legs: List[LedgerLeg], reference_type: str, reference_id: UUID) -> UUID:
        """Grava uma operação inteira: todas as pernas, com o mesmo operation_id.

        Para conta de CLIENTE, atualiza o saldo materializado e carimba o
        `balance_after` da linha — é o que o extrato mostra. Quem chama
        TEM que ter travado essas contas antes (AccountRepository.
        lock_customer_accounts); este método não trava nada, só escreve.

        Para conta INTERNAL, só grava a linha: o saldo dela é a soma.

        A conferência de soma zero aqui em Python é redundante com o
        trigger do banco, de propósito: o trigger só dispara no COMMIT, e
        o erro chegaria longe do código que o causou. Aqui ele estoura na
        linha certa.
        """
        total = sum(leg.amount for leg in legs)
        if total != 0:
            raise ValueError(f"Lançamento desbalanceado: as pernas somam {total}")

        operation_id = uuid4()

        for leg in legs:
            entry = LedgerEntry()
            entry.operation_id = operation_id
            entry.account_id = leg.account.id
            entry.amount = leg.amount
            entry.type = leg.entry_type
            entry.method = leg.method
            entry.reference_type = reference_type
            entry.reference_id = reference_id
            entry.external_id = leg.external_id

            if leg.account.type == Account.CUSTOMER:
                leg.account.balance = leg.account.balance + leg.amount
                entry.balance_after = leg.account.balance

            self.session.add(entry)

        return operation_id

    def list_statement(
        self, account_id: UUID, limit: int, after: Optional[Tuple[datetime, str]]
    ) -> List[LedgerEntry]:
        """Uma página do extrato, do mais novo para o mais antigo, por keyset.

        Keyset e não offset (`?page=`), e o motivo é o extrato ser uma
        lista que CRESCE NO TOPO. Com offset, um PIX que cai enquanto o
        cliente vira da página 1 para a 2 empurra tudo uma posição para
        baixo: a última linha da página 1 reaparece no topo da página 2.
        Com keyset, a página 2 começa "depois desta linha aqui", e o que
        entrou no topo não mexe nela.

        `limit + 1`: a linha extra não sai na resposta, só diz se existe
        próxima página.
        """
        query = self.session.query(LedgerEntry).filter(LedgerEntry.account_id == account_id)

        if after is not None:
            after_created_at, after_id = after
            query = query.filter(
                tuple_(LedgerEntry.created_at, LedgerEntry.id) < tuple_(after_created_at, int(after_id))
            )

        query = query.order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())

        return query.limit(limit + 1).all()
