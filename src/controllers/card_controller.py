import hashlib
import hmac
import secrets
from uuid import uuid4

from constants import APP_ENV
from controllers.base_controller import BaseController
from dtos import CardDTO
from errors import (
    AccountNotActive,
    AccountNotFound,
    CardNotFound,
    CreditWalletRequired,
    InvalidActivationCode,
    InvalidResourceStatusTransition,
    PlasticCardOnly,
)
from models import AccountStatus, Card, CardStatus, CreditWalletStatus, OutboxEvent
from repositories import AccountRepository, CardRepository, CreditWalletRepository, OutboxRepository
from utils.db_retry import retry_on_deadlock
from utils.ids import parse_uuid

# Transições pelo PATCH /cards/{id}/status. EMBOSSING → ACTIVE NÃO está aqui
# de propósito: físico só ativa com o código (PATCH /cards/{id}/activate).
# Terminais (CANCELED, LOST, STOLEN, FRAUD) não têm saída: cartão perdido
# não é desbloqueado, é reemitido.
ALLOWED_TRANSITIONS = {
    CardStatus.EMBOSSING: {CardStatus.CANCELED, CardStatus.LOST, CardStatus.STOLEN},
    CardStatus.ACTIVE: {CardStatus.BLOCKED, CardStatus.CANCELED, CardStatus.LOST, CardStatus.STOLEN, CardStatus.FRAUD},
    CardStatus.BLOCKED: {CardStatus.ACTIVE, CardStatus.CANCELED, CardStatus.LOST, CardStatus.STOLEN, CardStatus.FRAUD},
}


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class CardController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.card_repository = CardRepository(self.context)
        self.wallet_repository = CreditWalletRepository(self.context)
        self.account_repository = AccountRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)

    @retry_on_deadlock()
    def create(self, raw_account_id: str, payload: dict) -> dict:
        """Emite o cartão. Virtual nasce ACTIVE; físico nasce EMBOSSING.

        Crédito ou múltiplo exige carteira ACTIVE na conta — é ela que tem
        o limite. O PAN nunca passa por aqui: guardamos o token e os
        quatro últimos dígitos (PCI DSS).

        O código de ativação do físico vai impresso na carta, junto do
        plástico. Como não há gráfica, ele sai na resposta FORA de
        produção — o mesmo atalho do sandbox da QI. O banco guarda só o hash.
        """
        account_key = parse_uuid(raw_account_id)
        locked = self.account_repository.lock_customer_accounts_by_key([account_key])
        account = locked.get(account_key)
        if account is None:
            raise AccountNotFound(raw_account_id)

        if account.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(account.key, account.status.enumerator)

        functions = payload["functions"]
        wallet_id = None
        if functions != Card.DEBIT:
            wallet = self.wallet_repository.get_live_by_account(account.id)
            if wallet is None or wallet.status.enumerator != CreditWalletStatus.ACTIVE:
                raise CreditWalletRequired()
            wallet_id = wallet.id

        card_type = payload["type"]
        activation_code = None
        fields = {
            "account_id": account.id,
            "wallet_id": wallet_id,
            "type": card_type,
            "pan_token": f"tok_{uuid4().hex}",
            "last4": f"{secrets.randbelow(10_000):04d}",
            "brand": payload.get("brand", "VISA"),
            "functions": functions,
            "card_name": payload.get("card_name"),
            "printed_name": payload["printed_name"].upper(),
        }

        if card_type == Card.PLASTIC:
            activation_code = f"{secrets.randbelow(1_000_000):06d}"
            fields["contactless_enabled"] = payload.get("contactless_enabled", True)
            fields["activation_code_hash"] = _hash_code(activation_code)
            status = CardStatus.EMBOSSING
        else:
            status = CardStatus.ACTIVE

        card = self.card_repository.create(fields, status)
        self._outbox(card, None)
        self.session.commit()

        body = CardDTO.card_to_dict(card)
        if activation_code is not None and APP_ENV != "production":
            body["activation_code"] = activation_code
        return body

    def get_by_id(self, raw_card_id: str) -> dict:
        return CardDTO.card_to_dict(self._get_or_raise(raw_card_id))

    def list_by_account(self, raw_account_id: str) -> dict:
        account_key = parse_uuid(raw_account_id)
        account = self.account_repository.get_customer_account(account_key) if account_key is not None else None
        if account is None:
            raise AccountNotFound(raw_account_id)
        return {"items": [CardDTO.card_to_dict(card) for card in self.card_repository.list_by_account(account.id)]}

    @retry_on_deadlock()
    def activate(self, raw_card_id: str, code: str) -> dict:
        card = self._lock_or_raise(raw_card_id)

        if card.type != Card.PLASTIC:
            raise PlasticCardOnly()

        if card.status.enumerator != CardStatus.EMBOSSING:
            raise InvalidResourceStatusTransition("Card", card.status.enumerator, CardStatus.ACTIVE)

        # compare_digest: comparar hash em tempo constante não vaza, pelo
        # tempo de resposta, quantos caracteres batiam.
        if not hmac.compare_digest(card.activation_code_hash, _hash_code(code)):
            raise InvalidActivationCode()

        self.card_repository.update_status(card, CardStatus.ACTIVE, "activation code")
        self._outbox(card, CardStatus.EMBOSSING)
        self.session.commit()

        return CardDTO.card_to_dict(card)

    @retry_on_deadlock()
    def update_status(self, raw_card_id: str, new_status: str, reason: str) -> dict:
        card = self._lock_or_raise(raw_card_id)
        old_status = card.status.enumerator

        if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
            raise InvalidResourceStatusTransition("Card", old_status, new_status)

        self.card_repository.update_status(card, new_status, reason)
        self._outbox(card, old_status)
        self.session.commit()

        return CardDTO.card_to_dict(card)

    def _get_or_raise(self, raw_card_id: str) -> Card:
        card_key = parse_uuid(raw_card_id)
        card = self.card_repository.get_by_key(card_key) if card_key is not None else None
        if card is None:
            raise CardNotFound(raw_card_id)
        return card

    def _lock_or_raise(self, raw_card_id: str) -> Card:
        """Ordem global: conta → carteira → cartão. Aqui não mexe na carteira."""
        card = self._get_or_raise(raw_card_id)
        self.account_repository.lock_customer_accounts([card.account_id])
        return self.card_repository.lock(card.id)

    def _outbox(self, card: Card, old_status) -> None:
        # Mesmo formato do webhook baas.*_card.card da QI: status e old_status.
        self.outbox_repository.add(
            OutboxEvent.CARD_STATUS_CHANGED,
            "card",
            card,
            {"type": card.type, "status": card.status.enumerator, "old_status": old_status},
        )
