from fastapi import Request
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import AccountController, TransferController
from utils.schema_handler import SchemaHandler

DEFAULT_LIMIT = 10


class AccountResource:
    def on_get_by_id(self, account_id: str) -> JSONResponse:
        controller = AccountController()
        account = controller.get_by_id(account_id)

        return JSONResponse(content=jsonable_encoder(account), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate("patch_account_status.json")
    def on_patch_status(self, account_id: str, payload: dict) -> JSONResponse:
        controller = AccountController()
        account = controller.update_status(account_id, payload["status"], payload["reason"])

        return JSONResponse(content=jsonable_encoder(account), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate_query_params("get_statement.json")
    def on_get_statement(self, account_id: str, request: Request) -> JSONResponse:
        """Extrato paginado por cursor. O envelope já vem pronto do controller,
        porque o cursor é decisão de como LER o ledger, não vocabulário de HTTP."""
        controller = AccountController()

        limit = int(request.query_params.get("limit", DEFAULT_LIMIT))
        cursor = request.query_params.get("cursor")

        statement = controller.get_statement(account_id, limit, cursor)

        return JSONResponse(content=jsonable_encoder(statement), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate_query_params("get_account_transfers.json")
    def on_get_transfers(self, account_id: str, request: Request) -> JSONResponse:
        controller = TransferController()

        limit = int(request.query_params.get("limit", DEFAULT_LIMIT))
        cursor = request.query_params.get("cursor")
        statuses = request.query_params.getlist("status")

        page = controller.list_by_account(account_id, statuses, limit, cursor)

        return JSONResponse(content=jsonable_encoder(page), status_code=http_status.HTTP_200_OK)
