from typing import Optional

from fastapi import Header, Request
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import AccountController, LoanController, TransferController
from utils.schema_handler import SchemaHandler

DEFAULT_LIMIT = 10


class AccountResource:
    def on_get_by_id(self, account_key: str) -> JSONResponse:
        controller = AccountController()
        account = controller.get_by_id(account_key)

        return JSONResponse(content=jsonable_encoder(account), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate("patch_account_status.json")
    def on_patch_status(self, account_key: str, payload: dict) -> JSONResponse:
        controller = AccountController()
        account = controller.update_status(account_key, payload["status"], payload["reason"])

        return JSONResponse(content=jsonable_encoder(account), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate_query_params("get_statement.json")
    def on_get_statement(self, account_key: str, request: Request) -> JSONResponse:
        """Extrato paginado por cursor. O envelope já vem pronto do controller,
        porque o cursor é decisão de como LER o ledger, não vocabulário de HTTP."""
        controller = AccountController()

        limit = int(request.query_params.get("limit", DEFAULT_LIMIT))
        cursor = request.query_params.get("cursor")

        statement = controller.get_statement(account_key, limit, cursor)

        return JSONResponse(content=jsonable_encoder(statement), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate_query_params("get_account_transfers.json")
    def on_get_transfers(self, account_key: str, request: Request) -> JSONResponse:
        controller = TransferController()

        limit = int(request.query_params.get("limit", DEFAULT_LIMIT))
        cursor = request.query_params.get("cursor")
        statuses = request.query_params.getlist("status")

        page = controller.list_by_account(account_key, statuses, limit, cursor)

        return JSONResponse(content=jsonable_encoder(page), status_code=http_status.HTTP_200_OK)


class LoanResource:
    """Microcrédito: simulação, contratação, consulta e pagamento."""

    @SchemaHandler.validate("post_loan_simulation.json")
    def on_post_simulation(self, account_key: str, payload: dict) -> JSONResponse:
        simulation = LoanController().simulate(account_key, payload)
        return JSONResponse(content=jsonable_encoder(simulation), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate("post_loan.json")
    def on_post(
        self,
        account_key: str,
        payload: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        loan, created = LoanController().create(account_key, payload, idempotency_key)
        status_code = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
        return JSONResponse(content=jsonable_encoder(loan), status_code=status_code)

    @SchemaHandler.validate_query_params("get_account_loans.json")
    def on_get_by_account(self, account_key: str, request: Request) -> JSONResponse:
        limit = int(request.query_params.get("limit", DEFAULT_LIMIT))
        cursor = request.query_params.get("cursor")
        statuses = request.query_params.getlist("status")
        page = LoanController().list_by_account(account_key, statuses, limit, cursor)
        return JSONResponse(content=jsonable_encoder(page), status_code=http_status.HTTP_200_OK)

    def on_get_by_id(self, loan_key: str) -> JSONResponse:
        loan = LoanController().get_by_id(loan_key)
        return JSONResponse(content=jsonable_encoder(loan), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate("post_loan_payment.json")
    def on_post_payment(
        self,
        loan_key: str,
        payload: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        payment, created = LoanController().pay(loan_key, payload, idempotency_key)
        status_code = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
        return JSONResponse(content=jsonable_encoder(payment), status_code=status_code)
