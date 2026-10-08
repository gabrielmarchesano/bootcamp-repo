from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import CreditLineController, CustomerController
from utils.schema_handler import SchemaHandler


class CustomerResource:
    """Cadastro de cliente. Um método por rota: valida (decorator), chama o controller, devolve.

    O nome de cada parâmetro tem de ser o MESMO do `{...}` da rota no
    app.py: é assim que o FastAPI liga o pedaço do endereço ao argumento.
    Nome diferente vira query string obrigatória, e a rota responde 400.
    """

    @SchemaHandler.validate("post_customer.json")
    def on_post(self, payload: dict) -> JSONResponse:
        controller = CustomerController()
        customer = controller.create(payload)

        return JSONResponse(content=jsonable_encoder(customer), status_code=http_status.HTTP_201_CREATED)

    def on_get_by_id(self, customer_key: str) -> JSONResponse:
        controller = CustomerController()
        customer = controller.get_by_id(customer_key)

        return JSONResponse(content=jsonable_encoder(customer), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate("patch_customer.json")
    def on_patch_by_id(self, customer_key: str, payload: dict) -> JSONResponse:
        controller = CustomerController()
        customer = controller.update_revenue(customer_key, payload["annual_revenue"])

        return JSONResponse(content=jsonable_encoder(customer), status_code=http_status.HTTP_200_OK)

    def on_post_account(self, customer_key: str) -> JSONResponse:
        """Abre uma conta adicional para um titular que já existe (v7)."""
        controller = CustomerController()
        account = controller.open_account(customer_key)

        return JSONResponse(content=jsonable_encoder(account), status_code=http_status.HTTP_201_CREATED)

    def on_get_accounts(self, customer_key: str) -> JSONResponse:
        controller = CustomerController()
        accounts = controller.list_accounts(customer_key)

        return JSONResponse(content=jsonable_encoder(accounts), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate("post_customer_relationship.json")
    def on_post_relationship(self, customer_key: str, payload: dict) -> JSONResponse:
        """Cria um vínculo PARTNER/ADMINISTRATOR/ATTORNEY (PJ -> PF)."""
        controller = CustomerController()
        relationship = controller.create_relationship(customer_key, payload)

        return JSONResponse(content=jsonable_encoder(relationship), status_code=http_status.HTTP_201_CREATED)

    # ── linha de microcrédito do patrimônio ─────────────────────────

    @SchemaHandler.validate("put_credit_line.json")
    def on_put_credit_line(self, customer_key: str, payload: dict) -> JSONResponse:
        line = CreditLineController().upsert(customer_key, payload)
        return JSONResponse(content=jsonable_encoder(line), status_code=http_status.HTTP_200_OK)

    def on_get_credit_line(self, customer_key: str) -> JSONResponse:
        line = CreditLineController().get(customer_key)
        return JSONResponse(content=jsonable_encoder(line), status_code=http_status.HTTP_200_OK)
