from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from constants import OWN_ISPB
from controllers.base_controller import BaseController
from dtos import PixDTO
from errors import (
    AccountNotActive,
    AccountNotFound,
    InvalidParameter,
    PixKeyAlreadyRegistered,
    PixKeyLimitReached,
    PixKeyNotFound,
    PixKeyNotOwned,
)
from models import AccountStatus, Customer, OutboxEvent, PixKey, PixKeyInquiry, PixKeyStatus
from repositories import AccountRepository, OutboxRepository, PixKeyRepository
from utils.db_retry import retry_on_deadlock
from utils.dict_mock import lookup_external
from utils.ids import parse_uuid
from utils.pix import detect_key_type, generate_end_to_end_id, mask_document

# Regulamento Pix: até 5 chaves por conta de pessoa física, 20 de pessoa jurídica.
# No v7 o teto é por person_type do titular (NATURAL/LEGAL).
KEY_LIMIT = {Customer.NATURAL: 5, Customer.LEGAL: 20}

# Por quanto tempo o end_to_end_id de uma consulta vale para um Pix.
# A QI não publica o número; 15 minutos é premissa do time.
INQUIRY_TTL = timedelta(minutes=15)


class PixKeyController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.pix_key_repository = PixKeyRepository(self.context)
        self.account_repository = AccountRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)

    @retry_on_deadlock()
    def create(self, raw_account_id: str, payload: dict) -> dict:
        """Registra uma chave. CPF/CNPJ só a do próprio titular; EVP quem gera somos nós.

        O lock da conta serializa duas criações paralelas na mesma conta, o
        que mantém o teto de chaves honesto. A unicidade da chave entre
        contas é do banco (índice parcial ux_pix_key_active).
        """
        account_id = parse_uuid(raw_account_id)
        locked = self.account_repository.lock_customer_accounts([account_id]) if account_id is not None else {}
        account = locked.get(account_id)
        if account is None:
            raise AccountNotFound(raw_account_id)

        if account.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(account.id, account.status.enumerator)

        key_type = payload["key_type"]
        key_value = self._key_value(account, key_type, payload.get("key_value"))

        limit = KEY_LIMIT[account.customer.person_type]
        if len(self.pix_key_repository.list_active(account.id)) >= limit:
            raise PixKeyLimitReached(limit)

        if self.pix_key_repository.get_active_by_value(key_value) is not None:
            raise PixKeyAlreadyRegistered(key_value)

        try:
            pix_key = self.pix_key_repository.create(account.id, key_type, key_value)
        except IntegrityError:
            self.session.rollback()
            raise PixKeyAlreadyRegistered(key_value)

        self.outbox_repository.add(
            OutboxEvent.PIX_KEY_STATUS_CHANGED, "pix_key", pix_key.id, {"key_type": key_type, "status": PixKeyStatus.ACTIVE}
        )
        self.session.commit()

        return PixDTO.key_to_dict(pix_key)

    def list_by_account(self, raw_account_id: str) -> dict:
        account = self._get_account(raw_account_id)
        keys = self.pix_key_repository.list_active(account.id)
        return {"items": [PixDTO.key_to_dict(key) for key in keys]}

    @retry_on_deadlock()
    def delete(self, raw_account_id: str, raw_pix_key_id: str) -> dict:
        account = self._get_account(raw_account_id)
        pix_key_id = parse_uuid(raw_pix_key_id)
        pix_key = self.pix_key_repository.get_by_id(pix_key_id) if pix_key_id is not None else None

        if pix_key is None or pix_key.account_id != account.id or pix_key.status.enumerator != PixKeyStatus.ACTIVE:
            raise PixKeyNotFound(raw_pix_key_id)

        self.pix_key_repository.delete(pix_key, "customer request")
        self.outbox_repository.add(
            OutboxEvent.PIX_KEY_STATUS_CHANGED, "pix_key", pix_key.id, {"key_type": pix_key.key_type, "status": PixKeyStatus.DELETED}
        )
        self.session.commit()

        return PixDTO.key_to_dict(pix_key)

    def lookup(self, pix_key: str, raw_account_id: str) -> dict:
        """Consulta ao DICT (QI: GET /pix_key/{key}?account_key=).

        Grava a consulta e devolve o `end_to_end_id` que o Pix por chave vai
        ter de usar. Chave nossa resolve na tabela pix_key; chave de fora,
        no DICT mock (utils/dict_mock.py).
        """
        account = self._get_account(raw_account_id)

        key_type = detect_key_type(pix_key)
        if key_type is None:
            raise InvalidParameter(f"{pix_key} is not a valid Pix key")

        own_key = self.pix_key_repository.get_active_by_value(pix_key)
        if own_key is not None:
            data = self._own_key_data(own_key)
        else:
            data = lookup_external(pix_key)
            if data is None:
                raise PixKeyNotFound(pix_key)
            data = dict(data)
            data["owner_masked_document"] = mask_document(data.pop("owner_document"))
            data["destination_account_id"] = None

        now = datetime.now(timezone.utc)
        inquiry = self.pix_key_repository.create_inquiry(
            account_id=account.id,
            pix_key=pix_key,
            key_type=key_type,
            end_to_end_id=generate_end_to_end_id(now=now),
            expires_at=now + INQUIRY_TTL,
            **data,
        )
        self.session.commit()

        return PixDTO.inquiry_to_dict(inquiry)

    def _own_key_data(self, own_key: PixKey) -> dict:
        destination = own_key.account
        customer = destination.customer
        # v7: `document` já é CPF (NATURAL) ou CNPJ (LEGAL). O person_type
        # do DICT segue o person_type do titular.
        owner_person_type = (
            PixKeyInquiry.LEGAL if customer.person_type == Customer.LEGAL else PixKeyInquiry.NATURAL
        )

        return {
            "ispb": OWN_ISPB,
            "account_branch": destination.branch,
            "account_number": destination.number,
            "account_digit": None,
            "account_type": PixKeyInquiry.CHECKING,
            "owner_name": customer.name,
            "owner_masked_document": mask_document(customer.document),
            "owner_person_type": owner_person_type,
            "destination_account_id": destination.id,
        }

    def _key_value(self, account, key_type: str, key_value):
        customer = account.customer

        if key_type == PixKey.EVP:
            return str(uuid4())

        if key_value is None:
            raise InvalidParameter(f"key_value is required for key_type {key_type}")

        # v7: a chave CPF/CNPJ precisa ser o `document` do próprio titular
        # (QIT001041). O document já é CPF ou CNPJ conforme o person_type.
        if key_type in (PixKey.CPF, PixKey.CNPJ) and key_value != customer.document:
            raise PixKeyNotOwned(key_type)

        if detect_key_type(key_value) != key_type:
            raise InvalidParameter(f"{key_value} is not a valid {key_type} key")

        return key_value

    def _get_account(self, raw_account_id: str):
        account_id = parse_uuid(raw_account_id)
        account = self.account_repository.get_customer_account(account_id) if account_id is not None else None
        if account is None:
            raise AccountNotFound(raw_account_id)
        return account