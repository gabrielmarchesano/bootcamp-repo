from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import CustomerController
from utils.schema_handler import SchemaHandler


class CustomerResource:
    """Cadastro de cliente. Um método por rota: valida (decorator), chama o controller, devolve."""

    @SchemaHandler.validate("post_customer.json")
    def on_post(self, payload: dict) -> JSONResponse:
        controller = CustomerController()
        customer = controller.create(payload)

        return JSONResponse(content=jsonable_encoder(customer), status_code=http_status.HTTP_201_CREATED)

    def on_get_by_id(self, customer_id: str) -> JSONResponse:
        controller = CustomerController()
        customer = controller.get_by_id(customer_id)

        return JSONResponse(content=jsonable_encoder(customer), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate("patch_customer.json")
    def on_patch_by_id(self, customer_id: str, payload: dict) -> JSONResponse:
        controller = CustomerController()
        customer = controller.update_revenue(customer_id, payload["annual_revenue"])

        return JSONResponse(content=jsonable_encoder(customer), status_code=http_status.HTTP_200_OK)
