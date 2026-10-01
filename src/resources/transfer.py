from typing import Optional

from fastapi import Header
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import TransferController
from utils.schema_handler import SchemaHandler


class TransferResource:
    @SchemaHandler.validate("post_transfer.json")
    def on_post(
        self,
        payload: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        """201 quando a transferência nasce agora; 200 quando é a repetição de uma que já existe.

        A diferença de status é o único jeito de quem chamou saber, sem
        ler o corpo, se o dinheiro andou AGORA ou se andou da outra vez.
        """
        controller = TransferController()
        transfer, created = controller.create(payload, idempotency_key)

        status_code = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK

        return JSONResponse(content=jsonable_encoder(transfer), status_code=status_code)

    def on_get_by_id(self, transfer_id: str) -> JSONResponse:
        controller = TransferController()
        transfer = controller.get_by_id(transfer_id)

        return JSONResponse(content=jsonable_encoder(transfer), status_code=http_status.HTTP_200_OK)
