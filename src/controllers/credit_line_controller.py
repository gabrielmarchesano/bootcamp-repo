from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import LoanDTO
from errors import CreditLineNotAtRoot, CreditLineNotFound, CustomerNotFound, OutOfMpoRule
from models import Customer, OutboxEvent
from repositories import CreditLineRepository, CustomerRepository, OutboxRepository
from utils.db_retry import retry_on_deadlock
from utils.ids import parse_uuid

# Guardrails do microcrédito produtivo orientado (Res. CMN 4.854/2020).
from constants import MPO_MAX_LIMIT

# O banco tem os mesmos tetos em CHECK; aqui eles viram 422 com o campo e a
# regra, em vez de um erro de constraint.
MPO_MAX_MONTHLY_RATE = Decimal("0.04")
MPO_MAX_FEE_RATE = Decimal("0.03")


class CreditLineController(BaseController):
    """A IF informa a linha do PATRIMÔNIO; nós só aplicamos os guardrails."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.customer_repository = CustomerRepository(self.context)
        self.credit_line_repository = CreditLineRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)

    @retry_on_deadlock()
    def upsert(self, raw_customer_id: str, payload: dict) -> dict:
        """PUT da linha: cria ou grava uma nova versão. Mesmo corpo, mesmo estado.

        O titular tem de ser a raiz do patrimônio: a PF (que cobre o EI/MEI
        dela) ou a sociedade. `available_limit` = limite − saldo de
        microcrédito do patrimônio, nunca negativo.
        """
        customer = self._get_customer_or_raise(raw_customer_id)

        if customer.owner_customer_id is not None:
            raise CreditLineNotAtRoot()

        self._check_mpo(payload)

        line = self.credit_line_repository.lock_by_customer(customer.id)
        balance = self.credit_line_repository.microcredit_balance(customer.id)
        available_limit = max(payload["total_limit"] - balance, 0)

        if line is None:
            try:
                line = self.credit_line_repository.create(customer.id, payload, available_limit)
            except IntegrityError:
                # Dois PUTs da primeira linha ao mesmo tempo: o UNIQUE decide,
                # e o perdedor vira uma atualização da linha que acabou de nascer.
                self.session.rollback()
                line = self.credit_line_repository.lock_by_customer(customer.id)
                self.credit_line_repository.update(line, payload, available_limit)
        elif not self._same_terms(line, payload):
            self.credit_line_repository.update(line, payload, available_limit)
        else:
            # PUT idempotente: nada mudou, nenhuma versão nova.
            self.session.rollback()
            return LoanDTO.credit_line_to_dict(line, customer, balance)

        self.outbox_repository.add(
            OutboxEvent.CREDIT_LINE_CHANGED,
            "credit_line",
            line,
            {
                "customer_id": str(customer.key),
                "version": line.version,
                "total_limit": line.total_limit,
                "available_limit": line.available_limit,
            },
        )
        self.session.commit()

        return LoanDTO.credit_line_to_dict(line, customer, balance)

    def get(self, raw_customer_id: str) -> dict:
        """A linha do patrimônio do titular; para EI/MEI, a do dono."""
        customer = self._get_customer_or_raise(raw_customer_id)
        root_id = customer.exposure_customer_id

        line = self.credit_line_repository.get_by_customer(root_id)
        if line is None:
            raise CreditLineNotFound(raw_customer_id)

        root = customer if root_id == customer.id else customer.owner
        balance = self.credit_line_repository.microcredit_balance(root_id)
        return LoanDTO.credit_line_to_dict(line, root, balance)

    # ── regras ──────────────────────────────────────────────────────

    def _check_mpo(self, payload: dict) -> None:
        if payload["total_limit"] > MPO_MAX_LIMIT:
            raise OutOfMpoRule("total_limit", f"must be at most {MPO_MAX_LIMIT} cents")

        if Decimal(str(payload["monthly_interest_rate"])) > MPO_MAX_MONTHLY_RATE:
            raise OutOfMpoRule("monthly_interest_rate", f"must be at most {MPO_MAX_MONTHLY_RATE}")

        if Decimal(str(payload["origination_fee_rate"])) > MPO_MAX_FEE_RATE:
            raise OutOfMpoRule("origination_fee_rate", f"must be at most {MPO_MAX_FEE_RATE}")

    def _same_terms(self, line, payload: dict) -> bool:
        return (
            line.total_limit == payload["total_limit"]
            and Decimal(line.monthly_interest_rate) == Decimal(str(payload["monthly_interest_rate"]))
            and Decimal(line.origination_fee_rate) == Decimal(str(payload["origination_fee_rate"]))
        )

    def _get_customer_or_raise(self, raw_customer_id: str) -> Customer:
        customer_key = parse_uuid(raw_customer_id)
        customer = self.customer_repository.get_by_key(customer_key) if customer_key is not None else None
        if customer is None:
            raise CustomerNotFound(raw_customer_id)
        return customer
