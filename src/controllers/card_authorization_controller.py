import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from controllers.base_controller import BaseController
from dtos import CardDTO
from errors import (
    AuthorizationNotFound,
    InvalidAuthorizationState,
    InvalidParameter,
    RefundExceedsCapture,
)
from models import (
    Account,
    AccountStatus,
    CardAuthorization,
    CardAuthorizationEvent,
    CardAuthorizationStatus,
    CardStatus,
    CreditWalletStatus,
    InvoiceItem,
    LedgerEntry,
    OutboxEvent,
)
from repositories import (
    AccountRepository,
    CalendarRepository,
    CardAuthorizationRepository,
    CardRepository,
    CreditWalletRepository,
    InvoiceRepository,
    LedgerLeg,
    LedgerRepository,
    OutboxRepository,
)
from utils.billing_cycle import cycle_for, split_installments
from utils.db_retry import retry_on_deadlock
from utils.ids import parse_uuid

# Por quanto tempo o HOLD/reserva vale sem captura (job expire_authorizations).
AUTHORIZATION_TTL = timedelta(days=7)

# Código de resposta ISO 8583 por motivo de recusa.
RESPONSE_CODES = {
    CardAuthorization.INSUFFICIENT_FUNDS: "51",
    CardAuthorization.INSUFFICIENT_LIMIT: "51",
    CardAuthorization.CARD_NOT_ACTIVE: "62",
    CardAuthorization.ACCOUNT_NOT_ACTIVE: "57",
    CardAuthorization.WALLET_NOT_ACTIVE: "57",
    CardAuthorization.FUNCTION_NOT_SUPPORTED: "57",
}
APPROVED_CODE = "00"
INVALID_CARD_CODE = "14"


class CardAuthorizationController(BaseController):
    """O lado emissor da rede de cartão.

    ────────────────────────────────────────────────────────────────
    DUAS REGRAS DE RESPOSTA
    ────────────────────────────────────────────────────────────────
    • `authorize` e `increment` respondem **200 sempre**, com aprovado ou
      negado no corpo. Recusa de negócio não é erro HTTP: a rede espera a
      decisão, e um 4xx seria lido como "emissor fora do ar" (a QI pede o
      mesmo ao parceiro: qualquer coisa diferente do status esperado vira
      a regra de indisponibilidade).
    • Captura, reversão e estorno podem responder 4xx: chegam DEPOIS da
      decisão, e o que pode dar errado ali é a mensagem (autorização que
      não existe, estorno maior que a captura).

    ────────────────────────────────────────────────────────────────
    O DINHEIRO, EVENTO POR EVENTO
    ────────────────────────────────────────────────────────────────
    Cada movimento é uma linha em card_authorization_event; os totais do
    agregado (authorized, captured, refunded) são a soma corrente deles.
    Enquanto a autorização está APPROVED existe um HOLD (débito, em
    account.held_balance) ou uma reserva (crédito, em wallet.used_limit)
    do tamanho de `authorized_amount`. A PRIMEIRA captura troca o HOLD
    pelo valor capturado; daí em diante não há mais HOLD.

    Ordem de lock: conta → carteira → autorização (a ordem global).
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.authorization_repository = CardAuthorizationRepository(self.context)
        self.card_repository = CardRepository(self.context)
        self.wallet_repository = CreditWalletRepository(self.context)
        self.account_repository = AccountRepository(self.context)
        self.invoice_repository = InvoiceRepository(self.context)
        self.ledger_repository = LedgerRepository(self.context)
        self.calendar_repository = CalendarRepository(self.context)
        self.outbox_repository = OutboxRepository(self.context)

    # ── autorização ──────────────────────────────────────────────────

    @retry_on_deadlock()
    def authorize(self, payload: dict) -> dict:
        authorization_id = payload["authorization_id"]

        existing = self.authorization_repository.get_by_authorization_id(authorization_id)
        if existing is not None:
            return existing.response_payload

        card_key = parse_uuid(payload["card_id"])
        card = self.card_repository.get_by_key(card_key) if card_key is not None else None
        if card is None:
            # Cartão que não existe não vira linha (a FK não deixaria):
            # a resposta é determinística, então a repetição dá o mesmo.
            return {
                "authorization_id": authorization_id,
                "status": CardAuthorizationStatus.DECLINED,
                "response_code": INVALID_CARD_CODE,
                "approval_code": None,
                "denial_reason": "INVALID_CARD",
                "authorized_amount": 0,
            }

        account, wallet = self._lock_account_and_wallet(card)

        existing = self.authorization_repository.get_by_authorization_id(authorization_id)
        if existing is not None:
            return existing.response_payload

        function = payload["function"]
        amount = payload["amount"]
        denial = self._denial_reason(card, account, wallet, function, amount)

        fields = {
            "authorization_id": authorization_id,
            "card_id": card.id,
            "account_id": account.id,
            "function": function,
            "amount": amount,
            "installment_count": payload.get("installment_count", 1),
            "merchant_name": payload.get("merchant_name"),
            "mcc": payload.get("mcc"),
        }

        if denial is not None:
            fields.update(authorized_amount=0, response_code=RESPONSE_CODES[denial], denial_reason=denial)
            status = CardAuthorizationStatus.DECLINED
        else:
            fields.update(
                authorized_amount=amount,
                response_code=APPROVED_CODE,
                approval_code=f"{secrets.randbelow(1_000_000):06d}",
                expires_at=datetime.now(timezone.utc) + AUTHORIZATION_TTL,
            )
            status = CardAuthorizationStatus.APPROVED

        fields["response_payload"] = {
            "authorization_id": authorization_id,
            "status": status,
            "response_code": fields["response_code"],
            "approval_code": fields.get("approval_code"),
            "denial_reason": denial,
            "authorized_amount": fields["authorized_amount"],
        }

        authorization = self.authorization_repository.create(fields, status)

        if denial is None:
            self._hold(account, wallet, function, amount)
            self.authorization_repository.add_event(
                authorization, CardAuthorizationEvent.AUTHORIZATION, amount, authorization_id
            )

        self._outbox(authorization, CardAuthorizationEvent.AUTHORIZATION, amount)
        self.session.commit()

        return authorization.response_payload

    @retry_on_deadlock()
    def increment(self, authorization_id: str, payload: dict) -> dict:
        """Autorização incremental (hotel, combustível): mais HOLD na mesma autorização."""
        request_id = payload["request_id"]
        authorization, account, wallet = self._lock_existing(authorization_id)

        if self.authorization_repository.get_event(CardAuthorizationEvent.INCREMENTAL_AUTHORIZATION, request_id):
            return self._decision(authorization, None)

        self._require_status(authorization, (CardAuthorizationStatus.APPROVED,), "incremental authorization")

        amount = payload["amount"]
        card = authorization.card
        denial = self._denial_reason(card, account, wallet, authorization.function, amount)
        if denial is not None:
            return self._decision(authorization, denial)

        self._hold(account, wallet, authorization.function, amount)
        authorization.authorized_amount = authorization.authorized_amount + amount
        self.authorization_repository.add_event(
            authorization, CardAuthorizationEvent.INCREMENTAL_AUTHORIZATION, amount, request_id
        )
        self._outbox(authorization, CardAuthorizationEvent.INCREMENTAL_AUTHORIZATION, amount)
        self.session.commit()

        return self._decision(authorization, None)

    @retry_on_deadlock()
    def reverse(self, authorization_id: str, payload: dict) -> dict:
        """Desfaz a autorização no todo (REVERSAL) ou em parte (PARTIAL_REVERSAL)."""
        request_id = payload["request_id"]
        authorization, account, wallet = self._lock_existing(authorization_id)

        for event_type in (CardAuthorizationEvent.REVERSAL, CardAuthorizationEvent.PARTIAL_REVERSAL):
            if self.authorization_repository.get_event(event_type, request_id):
                return CardDTO.authorization_to_dict(authorization)

        self._require_status(authorization, (CardAuthorizationStatus.APPROVED,), "reversal")

        amount = payload.get("amount", authorization.authorized_amount)
        if amount > authorization.authorized_amount:
            raise InvalidParameter(
                f"amount {amount} is above the authorized amount {authorization.authorized_amount}"
            )

        self._release(account, wallet, authorization.function, amount)
        authorization.authorized_amount = authorization.authorized_amount - amount

        if authorization.authorized_amount == 0:
            event_type = CardAuthorizationEvent.REVERSAL
            self.authorization_repository.update_status(authorization, CardAuthorizationStatus.REVERSED, request_id)
        else:
            event_type = CardAuthorizationEvent.PARTIAL_REVERSAL

        self.authorization_repository.add_event(authorization, event_type, amount, request_id)
        self._outbox(authorization, event_type, amount)
        self.session.commit()

        return CardDTO.authorization_to_dict(authorization)

    # ── captura e estorno ────────────────────────────────────────────

    @retry_on_deadlock()
    def capture(self, payload: dict) -> dict:
        """Liquida a compra. Pode ser diferente do autorizado (gorjeta,
        combustível): a QI aceita, então não há trava de valor aqui.

        Débito: solta o HOLD e lança DEBIT_PURCHASE contra CARD_SETTLEMENT.
        A captura é mandatória — se o saldo não cobrir, a conta negativa
        (por isso não há CHECK balance >= 0 na tabela account).
        Crédito: troca a reserva pelo valor capturado e lança as parcelas
        nas faturas da carteira (atual e futuras).
        """
        capture_id = payload["capture_id"]
        authorization, account, wallet = self._lock_existing(payload["authorization_id"])

        if self.authorization_repository.get_event(CardAuthorizationEvent.CAPTURE, capture_id):
            return CardDTO.authorization_to_dict(authorization)

        self._require_status(
            authorization, (CardAuthorizationStatus.APPROVED, CardAuthorizationStatus.CAPTURED), "capture"
        )

        amount = payload["amount"]
        hold_outstanding = authorization.authorized_amount if self._is_approved(authorization) else 0

        if authorization.function == CardAuthorization.DEBIT:
            self._release(account, None, CardAuthorization.DEBIT, hold_outstanding)
            settlement = self.account_repository.get_internal(Account.CARD_SETTLEMENT)
            legs = [
                LedgerLeg(account, -amount, LedgerEntry.DEBIT_PURCHASE, "CARD", capture_id),
                LedgerLeg(settlement, amount, LedgerEntry.DEBIT_PURCHASE, "CARD", capture_id),
            ]
            self.ledger_repository.post(legs, LedgerEntry.REF_CARD_AUTHORIZATION, authorization.id)
        else:
            self.wallet_repository.change_used_limit(wallet, amount - hold_outstanding)
            self._post_installments(wallet, authorization, amount)

        authorization.captured_amount = authorization.captured_amount + amount
        if self._is_approved(authorization):
            self.authorization_repository.update_status(authorization, CardAuthorizationStatus.CAPTURED, capture_id)

        self.authorization_repository.add_event(authorization, CardAuthorizationEvent.CAPTURE, amount, capture_id)
        self._outbox(authorization, CardAuthorizationEvent.CAPTURE, amount)
        self.session.commit()

        return CardDTO.authorization_to_dict(authorization)

    @retry_on_deadlock()
    def refund(self, payload: dict) -> dict:
        """Estorno de compra capturada. É EVENTO: a autorização segue CAPTURED
        (o "completed" da QI), e quanto voltou diz o `refunded_amount`."""
        refund_id = payload["refund_id"]
        authorization, account, wallet = self._lock_existing(payload["authorization_id"])

        for event_type in (CardAuthorizationEvent.REFUND, CardAuthorizationEvent.PARTIAL_REFUND):
            if self.authorization_repository.get_event(event_type, refund_id):
                return CardDTO.authorization_to_dict(authorization)

        self._require_status(authorization, (CardAuthorizationStatus.CAPTURED,), "refund")

        amount = payload["amount"]
        total = authorization.refunded_amount + amount
        if total > authorization.captured_amount:
            raise RefundExceedsCapture(total, authorization.captured_amount)

        if authorization.function == CardAuthorization.DEBIT:
            settlement = self.account_repository.get_internal(Account.CARD_SETTLEMENT)
            legs = [
                LedgerLeg(settlement, -amount, LedgerEntry.PURCHASE_REFUND, "CARD", refund_id),
                LedgerLeg(account, amount, LedgerEntry.PURCHASE_REFUND, "CARD", refund_id),
            ]
            self.ledger_repository.post(legs, LedgerEntry.REF_CARD_AUTHORIZATION, authorization.id)
        else:
            self.wallet_repository.change_used_limit(wallet, -amount)
            today = self.calendar_repository.local_now().date()
            invoice = self._invoice_for(wallet, today, 1)
            self.invoice_repository.add_item(
                invoice, authorization.id, InvoiceItem.PURCHASE_REFUND, -amount, 1, 1,
                f"Estorno {authorization.merchant_name or ''}".strip(),
            )

        authorization.refunded_amount = total
        event_type = (
            CardAuthorizationEvent.REFUND if total == authorization.captured_amount else CardAuthorizationEvent.PARTIAL_REFUND
        )
        self.authorization_repository.add_event(authorization, event_type, amount, refund_id)
        self._outbox(authorization, event_type, amount)
        self.session.commit()

        return CardDTO.authorization_to_dict(authorization)

    @retry_on_deadlock()
    def expire(self, authorization_id: str) -> bool:
        """APPROVED → EXPIRED (job expire_authorizations): solta o HOLD ou a reserva.

        Mesma ordem de lock da captura. Se a autorização foi capturada ou
        desfeita enquanto o job rodava, o status já não é APPROVED e nada
        acontece. Devolve True se expirou agora.
        """
        authorization, account, wallet = self._lock_existing(authorization_id)

        if not self._is_approved(authorization) or authorization.expires_at is None:
            self.session.rollback()
            return False

        if authorization.expires_at > datetime.now(timezone.utc):
            self.session.rollback()
            return False

        amount = authorization.authorized_amount
        self._release(account, wallet, authorization.function, amount)
        self.authorization_repository.update_status(authorization, CardAuthorizationStatus.EXPIRED, "expires_at")
        if amount > 0:
            self.authorization_repository.add_event(authorization, CardAuthorizationEvent.EXPIRATION, amount, None)
        self._outbox(authorization, CardAuthorizationEvent.EXPIRATION, amount)
        self.session.commit()
        return True

    def get_by_authorization_id(self, authorization_id: str) -> dict:
        authorization = self.authorization_repository.get_by_authorization_id(authorization_id)
        if authorization is None:
            raise AuthorizationNotFound(authorization_id)
        return CardDTO.authorization_to_dict(authorization)

    # ── peças ────────────────────────────────────────────────────────

    def _denial_reason(self, card, account, wallet, function: str, amount: int) -> Optional[str]:
        """A primeira regra que falha decide o motivo. A ordem vai do cartão ao dinheiro."""
        if not card.supports(function):
            return CardAuthorization.FUNCTION_NOT_SUPPORTED

        if card.status.enumerator != CardStatus.ACTIVE:
            return CardAuthorization.CARD_NOT_ACTIVE

        if account.status.enumerator != AccountStatus.ACTIVE:
            return CardAuthorization.ACCOUNT_NOT_ACTIVE

        if function == CardAuthorization.CREDIT:
            if wallet is None or wallet.status.enumerator != CreditWalletStatus.ACTIVE:
                return CardAuthorization.WALLET_NOT_ACTIVE
            if amount > wallet.available_limit:
                return CardAuthorization.INSUFFICIENT_LIMIT
        elif amount > account.available_balance:
            return CardAuthorization.INSUFFICIENT_FUNDS

        return None

    def _hold(self, account, wallet, function: str, amount: int) -> None:
        if function == CardAuthorization.DEBIT:
            account.held_balance = account.held_balance + amount
        else:
            self.wallet_repository.change_used_limit(wallet, amount)

    def _release(self, account, wallet, function: str, amount: int) -> None:
        if amount <= 0:
            return
        if function == CardAuthorization.DEBIT:
            account.held_balance = max(account.held_balance - amount, 0)
        else:
            self.wallet_repository.change_used_limit(wallet, -amount)

    def _post_installments(self, wallet, authorization: CardAuthorization, amount: int) -> None:
        today = self.calendar_repository.local_now().date()
        installments = split_installments(amount, authorization.installment_count)
        description = authorization.merchant_name or "Compra no crédito"

        for number, value in enumerate(installments, start=1):
            invoice = self._invoice_for(wallet, today, number)
            self.invoice_repository.add_item(
                invoice, authorization.id, InvoiceItem.PURCHASE, value, number, len(installments), description
            )

    def _invoice_for(self, wallet, purchase_date, installment_number: int):
        closing, due = cycle_for(purchase_date, wallet.closing_day, wallet.due_day, installment_number)
        due = self.calendar_repository.next_business_day_on_or_after(due)
        return self.invoice_repository.get_or_create(wallet, closing.replace(day=1), closing, due)

    def _lock_account_and_wallet(self, card):
        locked = self.account_repository.lock_customer_accounts([card.account_id])
        account = locked[card.account_id]
        wallet = self.wallet_repository.lock(card.wallet_id) if card.wallet_id is not None else None
        return account, wallet

    def _lock_existing(self, authorization_id: str):
        authorization = self.authorization_repository.get_by_authorization_id(authorization_id)
        if authorization is None:
            raise AuthorizationNotFound(authorization_id)

        account, wallet = self._lock_account_and_wallet(authorization.card)
        authorization = self.authorization_repository.lock_by_authorization_id(authorization_id)
        return authorization, account, wallet

    def _require_status(self, authorization: CardAuthorization, allowed: tuple, operation: str) -> None:
        if authorization.status.enumerator not in allowed:
            raise InvalidAuthorizationState(authorization.status.enumerator, operation)

    def _is_approved(self, authorization: CardAuthorization) -> bool:
        return authorization.status.enumerator == CardAuthorizationStatus.APPROVED

    def _decision(self, authorization: CardAuthorization, denial: Optional[str]) -> dict:
        body = CardDTO.authorization_to_dict(authorization)
        body["decision"] = "DECLINED" if denial is not None else "APPROVED"
        body["decision_response_code"] = RESPONSE_CODES[denial] if denial is not None else APPROVED_CODE
        body["decision_denial_reason"] = denial
        return body

    def _outbox(self, authorization: CardAuthorization, event_type: str, amount: int) -> None:
        self.outbox_repository.add(
            OutboxEvent.CARD_AUTHORIZATION,
            "card_authorization",
            authorization,
            {
                "authorization_id": authorization.authorization_id,
                "status": authorization.status.enumerator,
                "event_type": event_type,
                "amount": amount,
            },
        )