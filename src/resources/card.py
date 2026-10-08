from typing import Optional

from fastapi import Header, Request
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import CardAuthorizationController, CardController, CreditWalletController, InvoiceController
from utils.schema_handler import SchemaHandler


def _ok(body: dict, status_code: int = http_status.HTTP_200_OK) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(body), status_code=status_code)


class CreditWalletResource:
    @SchemaHandler.validate("post_credit_wallet.json")
    def on_post(self, account_key: str, payload: dict) -> JSONResponse:
        return _ok(CreditWalletController().create(account_key, payload), http_status.HTTP_201_CREATED)

    def on_get_by_id(self, wallet_key: str) -> JSONResponse:
        return _ok(CreditWalletController().get_by_id(wallet_key))

    @SchemaHandler.validate("patch_credit_wallet_limit.json")
    def on_patch_limit(self, wallet_key: str, payload: dict) -> JSONResponse:
        return _ok(CreditWalletController().update_limit(wallet_key, payload["total_limit"]))

    @SchemaHandler.validate("patch_credit_wallet_status.json")
    def on_patch_status(self, wallet_key: str, payload: dict) -> JSONResponse:
        return _ok(CreditWalletController().update_status(wallet_key, payload["status"], payload["reason"]))

    @SchemaHandler.validate_query_params("get_wallet_invoices.json")
    def on_get_invoices(self, wallet_key: str, request: Request) -> JSONResponse:
        statuses = request.query_params.getlist("status")
        return _ok(CreditWalletController().list_invoices(wallet_key, statuses))

    def on_get_invoice(self, invoice_key: str) -> JSONResponse:
        return _ok(CreditWalletController().get_invoice(invoice_key))


class InvoiceResource:
    """Pagamento e encargo de fatura. Os dois movem dinheiro: Idempotency-Key."""

    @SchemaHandler.validate("post_invoice_payment.json")
    def on_post_payment(
        self,
        invoice_key: str,
        payload: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        body, created = InvoiceController().pay(invoice_key, payload, idempotency_key)
        return _ok(body, http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK)

    @SchemaHandler.validate("post_invoice_charge.json")
    def on_post_charge(
        self,
        invoice_key: str,
        payload: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        body, created = InvoiceController().charge(invoice_key, payload, idempotency_key)
        return _ok(body, http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK)


class CardResource:
    @SchemaHandler.validate("post_card.json")
    def on_post(self, account_key: str, payload: dict) -> JSONResponse:
        return _ok(CardController().create(account_key, payload), http_status.HTTP_201_CREATED)

    def on_get_by_account(self, account_key: str) -> JSONResponse:
        return _ok(CardController().list_by_account(account_key))

    def on_get_by_id(self, card_key: str) -> JSONResponse:
        return _ok(CardController().get_by_id(card_key))

    @SchemaHandler.validate("patch_card_activate.json")
    def on_patch_activate(self, card_key: str, payload: dict) -> JSONResponse:
        return _ok(CardController().activate(card_key, payload["code"]))

    @SchemaHandler.validate("patch_card_status.json")
    def on_patch_status(self, card_key: str, payload: dict) -> JSONResponse:
        return _ok(CardController().update_status(card_key, payload["status"], payload["reason"]))


class CardAuthorizationResource:
    """Rotas da processadora. Autorização e incremental: 200 sempre.

    A chave do caminho ({authorization_key}) é o `authorization_id` da rede.
    """

    @SchemaHandler.validate("post_card_authorization.json")
    def on_post(self, payload: dict) -> JSONResponse:
        return _ok(CardAuthorizationController().authorize(payload))

    def on_get(self, authorization_key: str) -> JSONResponse:
        return _ok(CardAuthorizationController().get_by_authorization_id(authorization_key))

    @SchemaHandler.validate("post_card_authorization_increment.json")
    def on_post_increment(self, authorization_key: str, payload: dict) -> JSONResponse:
        return _ok(CardAuthorizationController().increment(authorization_key, payload))

    @SchemaHandler.validate("post_card_authorization_reversal.json")
    def on_post_reversal(self, authorization_key: str, payload: dict) -> JSONResponse:
        return _ok(CardAuthorizationController().reverse(authorization_key, payload))

    @SchemaHandler.validate("post_card_capture.json")
    def on_post_capture(self, payload: dict) -> JSONResponse:
        return _ok(CardAuthorizationController().capture(payload))

    @SchemaHandler.validate("post_card_refund.json")
    def on_post_refund(self, payload: dict) -> JSONResponse:
        return _ok(CardAuthorizationController().refund(payload))
