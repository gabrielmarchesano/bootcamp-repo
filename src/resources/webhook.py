from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import WebhookController
from utils.schema_handler import SchemaHandler


class WebhookResource:
    """Entradas dos trilhos de pagamento (mock).

    Protegido pelo INTERNAL-TOKEN, como todas as rotas internas. O
    contrato v6 previa assinatura HMAC (X-Signature) — que é o certo
    quando o trilho é de verdade e está fora da nossa rede. Fica para
    quando existir um SPI que não seja o nosso mock.
    """

    @SchemaHandler.validate("post_webhook_spi.json")
    def on_post_spi(self, payload: dict) -> JSONResponse:
        controller = WebhookController()
        result = controller.spi_received(payload)

        return JSONResponse(content=jsonable_encoder(result), status_code=http_status.HTTP_200_OK)
