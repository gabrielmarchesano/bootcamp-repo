from fastapi import Request
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import CardAuthorizationController, CardController, CreditWalletController
from utils.schema_handler import SchemaHandler


def _ok(body: dict, status_code: int = http_status.HTTP_200_OK) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(body), status_code=status_code)


class CreditWalletResource:
    @SchemaHandler.validate("post_credit_wallet.json")
    def on_post(self, account_id: str, payload: dict) -> JSONResponse:
        return _ok(CreditWalletController().create(account_id, payload), http_status.HTTP_201_CREATED)

    def on_get_by_id(self, wallet_id: str) -> JSONResponse:
        return _ok(CreditWalletController().get_by_id(wallet_id))

    @SchemaHandler.validate("patch_credit_wallet_limit.json")
    def on_patch_limit(self, wallet_id: str, payload: dict) -> JSONResponse:
        return _ok(CreditWalletController().update_limit(wallet_id, payload["total_limit"]))

    @SchemaHandler.validate("patch_credit_wallet_status.json")
    def on_patch_status(self, wallet_id: str, payload: dict) -> JSONResponse:
        return _ok(CreditWalletController().update_status(wallet_id, payload["status"], payload["reason"]))

    @SchemaHandler.validate_query_params("get_wallet_invoices.json")
    def on_get_invoices(self, wallet_id: str, request: Request) -> JSONResponse:
        statuses = request.query_params.getlist("status")
        return _ok(CreditWalletController().list_invoices(wallet_id, statuses))

    def on_get_invoice(self, invoice_id: str) -> JSONResponse:
        return _ok(CreditWalletController().get_invoice(invoice_id))


class CardResource:
    @SchemaHandler.validate("post_card.json")
    def on_post(self, account_id: str, payload: dict) -> JSONResponse:
        return _ok(CardController().create(account_id, payload), http_status.HTTP_201_CREATED)

    def on_get_by_account(self, account_id: str) -> JSONResponse:
        return _ok(CardController().list_by_account(account_id))

    def on_get_by_id(self, card_id: str) -> JSONResponse:
        return _ok(CardController().get_by_id(card_id))

    @SchemaHandler.validate("patch_card_activate.json")
    def on_patch_activate(self, card_id: str, payload: dict) -> JSONResponse:
        return _ok(CardController().activate(card_id, payload["code"]))

    @SchemaHandler.validate("patch_card_status.json")
    def on_patch_status(self, card_id: str, payload: dict) -> JSONResponse:
        return _ok(CardController().update_status(card_id, payload["status"], payload["reason"]))


class CardAuthorizationResource:
    """Rotas da processadora. Autorização e incremental: 200 sempre."""

    @SchemaHandler.validate("post_card_authorization.json")
    def on_post(self, payload: dict) -> JSONResponse:
        return _ok(CardAuthorizationController().authorize(payload))

    def on_get(self, authorization_id: str) -> JSONResponse:
        return _ok(CardAuthorizationController().get_by_authorization_id(authorization_id))

    @SchemaHandler.validate("post_card_authorization_increment.json")
    def on_post_increment(self, authorization_id: str, payload: dict) -> JSONResponse:
        return _ok(CardAuthorizationController().increment(authorization_id, payload))

    @SchemaHandler.validate("post_card_authorization_reversal.json")
    def on_post_reversal(self, authorization_id: str, payload: dict) -> JSONResponse:
        return _ok(CardAuthorizationController().reverse(authorization_id, payload))

    @SchemaHandler.validate("post_card_capture.json")
    def on_post_capture(self, payload: dict) -> JSONResponse:
        return _ok(CardAuthorizationController().capture(payload))

    @SchemaHandler.validate("post_card_refund.json")
    def on_post_refund(self, payload: dict) -> JSONResponse:
        return _ok(CardAuthorizationController().refund(payload))