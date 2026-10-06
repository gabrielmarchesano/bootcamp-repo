from typing import Optional

from fastapi import Header, Request
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import PixKeyController, TransferController
from utils.schema_handler import SchemaHandler


def _transfer_status_code(transfer: dict, created: bool) -> int:
    """201 se o dinheiro já chegou (on-us), 202 se ainda vai pelo trilho, 200 se é repetição.

    É a mesma leitura da QI: 201 `sent`, 202 `pending` — e 202 quer dizer
    "não tente de novo; o desfecho chega por webhook".
    """
    if not created:
        return http_status.HTTP_200_OK
    if transfer["status"] == "COMPLETED":
        return http_status.HTTP_201_CREATED
    return http_status.HTTP_202_ACCEPTED


class PixResource:
    """Chaves Pix, consulta ao DICT, Pix de saída e devolução."""

    @SchemaHandler.validate("post_pix_key.json")
    def on_post_key(self, account_id: str, payload: dict) -> JSONResponse:
        pix_key = PixKeyController().create(account_id, payload)
        return JSONResponse(content=jsonable_encoder(pix_key), status_code=http_status.HTTP_201_CREATED)

    def on_get_keys(self, account_id: str) -> JSONResponse:
        keys = PixKeyController().list_by_account(account_id)
        return JSONResponse(content=jsonable_encoder(keys), status_code=http_status.HTTP_200_OK)

    def on_delete_key(self, account_id: str, pix_key_id: str) -> JSONResponse:
        pix_key = PixKeyController().delete(account_id, pix_key_id)
        return JSONResponse(content=jsonable_encoder(pix_key), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate_query_params("get_pix_key_lookup.json")
    def on_get_lookup(self, pix_key: str, request: Request) -> JSONResponse:
        inquiry = PixKeyController().lookup(pix_key, request.query_params.get("account_id"))
        return JSONResponse(content=jsonable_encoder(inquiry), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate("post_pix_transfer.json")
    def on_post_transfer(
        self,
        account_id: str,
        payload: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        transfer, created = TransferController().create_pix(account_id, payload, idempotency_key)
        return JSONResponse(content=jsonable_encoder(transfer), status_code=_transfer_status_code(transfer, created))

    @SchemaHandler.validate("post_pix_reversal.json")
    def on_post_reversal(
        self,
        account_id: str,
        incoming_transfer_id: str,
        payload: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        transfer, created = TransferController().create_pix_reversal(
            account_id, incoming_transfer_id, payload, idempotency_key
        )
        return JSONResponse(content=jsonable_encoder(transfer), status_code=_transfer_status_code(transfer, created))


class TedResource:
    @SchemaHandler.validate("post_ted_transfer.json")
    def on_post(
        self,
        account_id: str,
        payload: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        transfer, created = TransferController().create_ted(account_id, payload, idempotency_key)
        return JSONResponse(content=jsonable_encoder(transfer), status_code=_transfer_status_code(transfer, created))