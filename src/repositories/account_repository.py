from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, text

from database import Context
from models import Account, AccountStatus, AccountStatusEvent, Customer
from repositories.enumerator_repository import EnumeratorRepository


class AccountRepository:
    """Contas: as dos clientes e as internas do ledger.

    ────────────────────────────────────────────────────────────────
    A ORDEM GLOBAL DE LOCK MORA AQUI
    ────────────────────────────────────────────────────────────────
    `lock_customer_accounts` é a ÚNICA porta para travar conta de
    cliente com FOR UPDATE, e ela sempre trava em ordem crescente de id.

    Por quê: a transferência A→B trava A e B; a B→A, ao mesmo tempo,
    trava B e A. Se cada uma travasse na ordem em que as contas aparecem
    no pedido, a primeira seguraria A esperando B e a segunda seguraria B
    esperando A — deadlock. Travando sempre pelo menor id primeiro, as
    duas disputam a MESMA conta primeiro, uma espera a outra, e o ciclo
    não tem como se formar.

    Contas INTERNAL nunca são travadas: entram em quase todo lançamento e
    virariam uma fila única para o banco inteiro. O saldo delas é a soma
    do ledger (view vw_internal_account_balance).

    ────────────────────────────────────────────────────────────────
    E O HISTÓRICO DE STATUS TAMBÉM
    ────────────────────────────────────────────────────────────────
    Status da conta só muda por `create_for_customer` (nascimento) e
    `update_status` (transição). Os dois gravam o evento na mesma
    chamada, então não existe mudança de status sem linha em
    account_status_event. QUAIS transições são permitidas não é assunto
    daqui: isso é regra, e mora no AccountController.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.enumerators = EnumeratorRepository(context)

    def create_for_customer(self, customer: Customer, status: str, status_reason: str) -> Account:
        # Sem autoflush: a sequência não depende de nada pendente, e um flush
        # aqui mandaria o INSERT do cliente para o banco FORA do `try` do
        # controller que traduz CPF duplicado em 409 (vira 500 na corrida).
        with self.session.no_autoflush:
            next_number = self.session.execute(text("SELECT nextval('account_number_seq')")).scalar_one()

        account = Account()
        account.type = Account.CUSTOMER
        account.customer = customer
        account.branch = Account.DEFAULT_BRANCH
        account.number = str(next_number).zfill(8)
        account.status = self.enumerators.get(AccountStatus, status)
        account.status_reason = status_reason
        account.balance = 0
        account.held_balance = 0

        self.session.add(account)

        # Nascimento: null → status inicial (o "nulo ao nascer" do from_status_id).
        self._record_status_event(account, None, account.status, status_reason)

        return account

    def get_customer_account(self, account_id: UUID) -> Account:
        return (
            self.session.query(Account)
            .filter(Account.id == account_id, Account.type == Account.CUSTOMER)
            .first()
        )

    def get_customer_account_by_number(self, branch: str, number: str) -> Account:
        return (
            self.session.query(Account)
            .filter(Account.branch == branch, Account.number == number, Account.type == Account.CUSTOMER)
            .first()
        )

    def get_internal(self, internal_code: str) -> Account:
        return (
            self.session.query(Account)
            .filter(Account.internal_code == internal_code, Account.type == Account.INTERNAL)
            .one()
        )

    def lock_customer_accounts(self, account_ids: List[UUID]) -> Dict[UUID, Account]:
        """Trava as contas de cliente pedidas, uma a uma, em ordem crescente de id.

        Uma consulta por conta (e não um IN com ORDER BY) para que a ordem
        de travamento seja explícita no código, e não um detalhe do plano
        de execução do Postgres.

        O `populate_existing` é obrigatório: se a conta já estava na sessão
        (lida antes, sem lock), o SQLAlchemy devolveria o objeto antigo da
        memória, com o saldo de ANTES de esperar o lock. O lock seria real
        e o saldo, velho — o pior dos dois mundos.

        Conta que não existe (ou que é INTERNAL) simplesmente não aparece
        no dicionário devolvido; quem decide o que isso significa é o
        controller.
        """
        locked = {}

        for account_id in sorted(set(account_ids), key=str):
            account = (
                self.session.query(Account)
                .filter(Account.id == account_id, Account.type == Account.CUSTOMER)
                .populate_existing()
                .with_for_update()
                .first()
            )
            if account is not None:
                locked[account_id] = account

        return locked

    def update_status(self, account: Account, new_status: str, reason: str) -> None:
        """Muda o status E grava o evento — as duas coisas, sempre juntas.

        Quem chama já conferiu a transição (controller) e já travou a
        conta (lock_customer_accounts).
        """
        old_status = account.status

        account.status = self.enumerators.get(AccountStatus, new_status)
        account.status_reason = reason
        account.updated_at = func.now()

        self._record_status_event(account, old_status, account.status, reason)

    def has_active_loan(self, account_id: UUID) -> bool:
        # SQL direto: o model de Loan nasce no sprint de microcrédito.
        row = self.session.execute(
            text(
                "SELECT 1 FROM loan l JOIN loan_status s ON s.id = l.status_id "
                "WHERE l.account_id = :account_id AND s.enumerator = 'ACTIVE' LIMIT 1"
            ),
            {"account_id": account_id},
        ).first()
        return row is not None

    def _record_status_event(
        self,
        account: Account,
        from_status: Optional[AccountStatus],
        to_status: AccountStatus,
        reason: Optional[str],
    ) -> None:
        """Pendura o evento NA RELAÇÃO com a conta (e não por account_id solto).

        É a relação que diz ao SQLAlchemy "grave a conta antes do evento".
        Com só o account_id preenchido, ele pode gravar o evento primeiro e
        o banco recusaria pela chave estrangeira.
        """
        event = AccountStatusEvent()
        event.account = account
        event.from_status = from_status
        event.to_status = to_status
        event.reason = reason

        self.session.add(event)