from datetime import date

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import CustomerDTO
from errors import (
    CustomerAlreadyExists,
    CustomerNotFound,
    InvalidBirthdate,
    InvalidCnpj,
    InvalidDocumentNumber,
)
from models import Account, Customer, OutboxEvent
from repositories import AccountRepository, CustomerRepository, OutboxRepository
from utils.document_number import is_valid_cnpj, is_valid_cpf
from utils.ids import parse_uuid
from utils.kyc_mock import check_kyc

MINIMUM_AGE = 18
# A partir desta idade a conta abre em PENDING, para revisão manual da IF
# (proteção de idoso contra golpe e abuso financeiro).
REVIEW_AGE = 80

# Teto de faturamento para o microcrédito: R$ 360.000,00 por ano, em centavos.
# É o mesmo valor do CHECK ck_eligibility do banco — se um mudar, o outro muda.
MICROCREDIT_REVENUE_CAP = 36_000_000


class CustomerController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.customer_repository = CustomerRepository(self.context)
        self.account_repository = AccountRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)

    def create(self, customer_data: dict) -> dict:
        """Cadastra o cliente e abre a conta dele, na mesma transação.

        A ordem das perguntas segue o fluxo v6:
          1. o documento existe? (CPF e, para MEI, CNPJ)
          2. já é cliente?
          3. KYC/PLD
          4. idade
          5. elegibilidade ao microcrédito

        Recusa de KYC e de idade NÃO devolvem erro: o cadastro é criado com a conta em REJECTED e responde 201.
        O banco precisa guardar a tentativa — é trilha de auditoria de
        PLD, e a IF precisa conseguir consultar por que recusou.
        """
        self.logger.debug("Cadastrando cliente")

        cpf = customer_data["cpf"]
        cnpj = customer_data.get("cnpj")
        birth_date = self._parse_birth_date(customer_data["birth_date"])

        if not is_valid_cpf(cpf):
            raise InvalidDocumentNumber(cpf)

        if cnpj is not None and not is_valid_cnpj(cnpj):
            raise InvalidCnpj(cnpj)

        if self.customer_repository.get_by_cpf(cpf) is not None:
            raise CustomerAlreadyExists("cpf", cpf)

        if cnpj is not None and self.customer_repository.get_by_cnpj(cnpj) is not None:
            raise CustomerAlreadyExists("cnpj", cnpj)

        kyc_status = check_kyc(cpf)
        age = self._age_in_years(birth_date)
        is_pep = customer_data.get("is_pep", False)
        microcredit_eligible = customer_data["annual_revenue"] <= MICROCREDIT_REVENUE_CAP

        account_status, status_reason = self._initial_account_status(kyc_status, age, is_pep)

        customer = self.customer_repository.create(customer_data, birth_date, kyc_status, microcredit_eligible)
        account = self.account_repository.create_for_customer(customer, account_status, status_reason)

        try:
            self.session.flush()
        except IntegrityError as error:
            # Corrida: outro POST com o mesmo documento passou pelas
            # checagens ao mesmo tempo que este. O UNIQUE do banco é a
            # última palavra.
            self.session.rollback()
            if cnpj is not None and "cnpj" in str(error.orig):
                raise CustomerAlreadyExists("cnpj", cnpj)
            raise CustomerAlreadyExists("cpf", cpf)

        self.outbox_repository.add(
            OutboxEvent.ACCOUNT_OPENED,
            "account",
            account.id,
            {"customer_id": str(customer.id), "status": account_status, "reason": status_reason},
        )

        self.session.commit()

        return CustomerDTO.creation_to_dict(customer)

    def get_by_id(self, raw_customer_id: str) -> dict:
        customer = self._get_customer_or_raise(raw_customer_id)
        return CustomerDTO.obj_to_dict(customer)

    def update_revenue(self, raw_customer_id: str, annual_revenue: int) -> dict:
        """Atualiza o faturamento e recalcula a elegibilidade.

        Perder a elegibilidade não mexe em contrato já assinado: só bloqueia
        contratação NOVA (regra do sprint de microcrédito).
        """
        customer = self._get_customer_or_raise(raw_customer_id)

        microcredit_eligible = annual_revenue <= MICROCREDIT_REVENUE_CAP
        self.customer_repository.update_revenue(customer, annual_revenue, microcredit_eligible)

        self.session.commit()

        return CustomerDTO.obj_to_dict(customer)

    def _get_customer_or_raise(self, raw_customer_id: str) -> Customer:
        customer_id = parse_uuid(raw_customer_id)
        customer = None

        if customer_id is not None:
            customer = self.customer_repository.get_by_id(customer_id)

        if customer is None:
            raise CustomerNotFound(raw_customer_id)

        return customer

    def _initial_account_status(self, kyc_status: str, age: int, is_pep: bool):
        """O status de nascimento da conta, e o motivo dele.

        Recusa vem antes de revisão: um menor de idade que também é PEP
        é REJECTED, não PENDING — não existe revisão que o torne elegível.
        """
        if kyc_status == Customer.KYC_REJECTED:
            return Account.REJECTED, "KYC_REJECTED"

        if age < MINIMUM_AGE:
            return Account.REJECTED, "UNDERAGE"

        if is_pep:
            return Account.PENDING, "PEP_REVIEW"

        if age >= REVIEW_AGE:
            return Account.PENDING, "SENIOR_REVIEW"

        return Account.ACTIVE, None

    def _parse_birth_date(self, raw_birth_date: str) -> date:
        try:
            return date.fromisoformat(raw_birth_date)
        except ValueError:
            raise InvalidBirthdate(raw_birth_date)

    def _age_in_years(self, birth_date: date) -> int:
        today = date.today()
        age = today.year - birth_date.year

        if (today.month, today.day) < (birth_date.month, birth_date.day):
            age = age - 1

        return age
