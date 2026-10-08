from datetime import date

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import CustomerDTO
from errors import (
    AdditionalAccountNotAllowed,
    CustomerAlreadyExists,
    CustomerNotFound,
    InvalidBirthdate,
    InvalidCnpj,
    InvalidDocumentNumber,
    InvalidEiOwner,
    InvalidRelationship,
)
from models import AccountStatus, Customer, CustomerRelationship, KycStatus, OutboxEvent
from repositories import AccountRepository, CustomerRepository, OutboxRepository
from utils.document_number import is_valid_cnpj, is_valid_cpf
from utils.ids import parse_uuid
from utils.kyc_mock import check_kyc

MINIMUM_AGE = 18
# A partir desta idade a conta abre em PENDING, para revisão manual da IF
# (proteção de idoso contra golpe e abuso financeiro).
REVIEW_AGE = 80

VALID_ROLES = {CustomerRelationship.PARTNER, CustomerRelationship.ADMINISTRATOR, CustomerRelationship.ATTORNEY}

# O UNIQUE inline da coluna `document` no v7 autogera o nome
# `customer_document_key`. Qualquer OUTRA violação de integridade é bug
# nosso e tem de aparecer como bug (500 + erro real no log).
DOCUMENT_UNIQUE_CONSTRAINT = "customer_document_key"


class CustomerController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.customer_repository = CustomerRepository(self.context)
        self.account_repository = AccountRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)

    def create(self, customer_data: dict) -> dict:
        """Cadastra o titular v7 e abre a primeira conta dele, na mesma transação.

        A ordem das perguntas:
          1. o documento é um CPF/CNPJ válido (dígito verificador)?
          2. (EI) o dono informado é uma pessoa natural?
          3. já é cliente? (document duplicado)
          4. KYC/PLD
          5. idade (só NATURAL)

        Recusa de KYC e de idade NÃO devolvem erro: o cadastro é criado com
        a conta em REJECTED e responde 201 (trilha de auditoria de PLD).
        """
        self.logger.debug("Cadastrando titular v7")

        person_type = customer_data["person_type"]
        document = customer_data["document"]
        birth_date = self._parse_birth_date(customer_data.get("birth_date"))

        self._validate_document(person_type, document)

        self._validate_ei_owner(customer_data)

        if self.customer_repository.get_by_document(document) is not None:
            raise CustomerAlreadyExists("document", document)

        # KYC roda sobre o documento do próprio titular; idade só faz
        # sentido para pessoa natural (PJ não tem data de nascimento).
        kyc_status = check_kyc(document)
        is_pep = customer_data.get("is_pep", False)

        if person_type == Customer.NATURAL:
            age = self._age_in_years(birth_date)
        else:
            age = None

        account_status, status_reason = self._initial_account_status(kyc_status, age, is_pep)

        customer = self.customer_repository.create(customer_data, birth_date, kyc_status)
        account = self.account_repository.create_for_customer(customer, account_status, status_reason)

        try:
            self.session.flush()
        except IntegrityError as error:
            # Corrida: outro POST com o mesmo documento passou pelas
            # checagens ao mesmo tempo. O UNIQUE do banco é a última
            # palavra — mas SÓ a violação do documento vira 409.
            self.session.rollback()
            if self._is_document_violation(error):
                raise CustomerAlreadyExists("document", document)
            raise

        # Colunas GERADAS (microcredit_eligible, fee_segment, exposure_customer_id)
        # só existem depois do INSERT: o refresh as traz do banco.
        self.session.refresh(customer)

        self.outbox_repository.add(
            OutboxEvent.ACCOUNT_OPENED,
            "account",
            account.id,
            {"customer_id": str(customer.id), "status": account_status, "reason": status_reason},
        )

        self.session.commit()

        return CustomerDTO.creation_to_dict(customer, account)

    def get_by_id(self, raw_customer_id: str) -> dict:
        customer = self._get_customer_or_raise(raw_customer_id)
        return CustomerDTO.obj_to_dict(customer)

    def update_revenue(self, raw_customer_id: str, annual_revenue: int) -> dict:
        """Atualiza o faturamento. A elegibilidade (microcredit_eligible) é
        coluna gerada: o banco recalcula, e o refresh traz o novo valor.
        """
        customer = self._get_customer_or_raise(raw_customer_id)

        self.customer_repository.update_revenue(customer, annual_revenue)

        self.session.flush()
        self.session.refresh(customer)
        self.session.commit()

        return CustomerDTO.obj_to_dict(customer)

    # ── contas adicionais e vínculos (v7) ────────────────────────────

    def open_account(self, raw_customer_id: str) -> dict:
        """Abre uma conta ADICIONAL para um titular que já existe.

        Gatilho determinístico do QIT001051: o titular precisa ter o KYC
        APROVADO. A conta adicional reusa o kyc_status atual do titular —
        se ele não está aprovado, não há status ACTIVE a herdar e a regra
        de abertura é violada.
        """
        customer = self._get_customer_or_raise(raw_customer_id)

        if customer.kyc_status.enumerator != KycStatus.APPROVED:
            raise AdditionalAccountNotAllowed("holder KYC is not APPROVED")

        account = self.account_repository.create_for_customer(customer, AccountStatus.ACTIVE, None)

        self.session.flush()

        self.outbox_repository.add(
            OutboxEvent.ACCOUNT_OPENED,
            "account",
            account.id,
            {"customer_id": str(customer.id), "status": AccountStatus.ACTIVE, "reason": None},
        )

        self.session.commit()

        return CustomerDTO.account_to_dict(account)

    def list_accounts(self, raw_customer_id: str) -> dict:
        """Lista as contas do titular, mais antigas primeiro (determinístico)."""
        customer = self._get_customer_or_raise(raw_customer_id)
        return CustomerDTO.accounts_to_dict(customer.accounts)

    def create_relationship(self, raw_customer_id: str, payload: dict) -> dict:
        """Cria um vínculo PARTNER/ADMINISTRATOR/ATTORNEY entre a PJ do path
        (lado legal) e a PF informada (lado natural). QIT001052 (422) quando
        a natureza das pontas não bate ou o par já existe.
        """
        legal = self._get_customer_or_raise(raw_customer_id)
        role = payload["role"]

        if role not in VALID_ROLES:
            raise InvalidRelationship(f"unknown role {role}")

        if legal.person_type != Customer.LEGAL:
            raise InvalidRelationship("the path customer must be a LEGAL person")

        natural = self._get_customer_or_raise(payload["natural_customer_id"])

        if natural.person_type != Customer.NATURAL:
            raise InvalidRelationship("the related customer must be a NATURAL person")

        relationship = self.customer_repository.add_relationship(legal.id, natural.id, role)

        try:
            self.session.flush()
        except IntegrityError:
            # PK composta (legal, natural, role): par repetido.
            self.session.rollback()
            raise InvalidRelationship("relationship already exists")

        self.session.refresh(relationship)
        self.session.commit()

        return CustomerDTO.relationship_to_dict(relationship)

    # ── validações ───────────────────────────────────────────────────

    def _validate_document(self, person_type: str, document: str) -> None:
        if person_type == Customer.NATURAL:
            if not is_valid_cpf(document):
                raise InvalidDocumentNumber(document)
        else:
            if not is_valid_cnpj(document):
                raise InvalidCnpj(document)

    def _validate_ei_owner(self, customer_data: dict):
        """Só EI tem owner_customer_id (o schema já garante). O dono precisa
        existir e ser pessoa natural (QIT001050)."""
        owner_customer_id = customer_data.get("owner_customer_id")
        if owner_customer_id is None:
            return None

        owner_id = parse_uuid(owner_customer_id)
        owner = self.customer_repository.get_by_id(owner_id) if owner_id is not None else None

        if owner is None or owner.person_type != Customer.NATURAL:
            raise InvalidEiOwner(owner_customer_id)

        return owner

    def _get_customer_or_raise(self, raw_customer_id: str) -> Customer:
        customer_id = parse_uuid(raw_customer_id)
        customer = None

        if customer_id is not None:
            customer = self.customer_repository.get_by_id(customer_id)

        if customer is None:
            raise CustomerNotFound(raw_customer_id)

        return customer

    def _initial_account_status(self, kyc_status: str, age, is_pep: bool):
        """O status de nascimento da conta, e o motivo dele.

        Recusa vem antes de revisão. `age` é None para pessoa jurídica:
        idade não se aplica, e a PJ não é barrada por isso.
        """
        if kyc_status == KycStatus.REJECTED:
            return AccountStatus.REJECTED, "KYC_REJECTED"

        if age is not None and age < MINIMUM_AGE:
            return AccountStatus.REJECTED, "UNDERAGE"

        if is_pep:
            return AccountStatus.PENDING, "PEP_REVIEW"

        if age is not None and age >= REVIEW_AGE:
            return AccountStatus.PENDING, "SENIOR_REVIEW"

        return AccountStatus.ACTIVE, None

    def _is_document_violation(self, error: IntegrityError) -> bool:
        diag = getattr(error.orig, "diag", None)
        constraint_name = getattr(diag, "constraint_name", None)
        if constraint_name == DOCUMENT_UNIQUE_CONSTRAINT:
            return True
        # Nome não bateu: cai para a detecção robusta pela mensagem do
        # driver (evita hardcode frágil se o Postgres mudar o nome).
        message = str(getattr(error, "orig", error)).lower()
        return "document" in message and "unique" in message

    def _parse_birth_date(self, raw_birth_date):
        if raw_birth_date is None:
            return None
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
