import os

from connectors.rest_connector import RestConnector

# Onde a IF recebe os eventos (o webhook dela). Sem a variável, o despacho
# roda em modo mock: registra no log e considera entregue — é o que existe
# nesta entrega, em que a IF também é mock.
IF_WEBHOOK_URL = os.environ.get("IF_WEBHOOK_URL")
IF_WEBHOOK_TOKEN = os.environ.get("IF_WEBHOOK_TOKEN", "default_token")
IF_WEBHOOK_TIMEOUT = int(os.environ.get("IF_WEBHOOK_TIMEOUT", "5"))


class IfWebhookConnector(RestConnector):
    """Entrega os eventos do outbox à IF, no formato `webhook_type` da QI."""

    def __init__(self) -> None:
        super().__init__(__name__, IF_WEBHOOK_URL or "", IF_WEBHOOK_TIMEOUT, IF_WEBHOOK_TOKEN)
        if not IF_WEBHOOK_URL:
            self.logger.warning("IF_WEBHOOK_URL vazia: rodando em modo MOCK. Eventos não serão enviados de verdade.")

    def deliver(self, event_type: str, aggregate_type: str, aggregate_key: str, payload: dict, event_id: int) -> bool:
        """True se a IF confirmou (2xx). Timeout e erro de rede viram False: tenta de novo depois."""
        body = {
            "webhook_type": event_type,
            "key": aggregate_key,
            "aggregate_type": aggregate_type,
            "event_id": event_id,
            "data": payload,
        }

        if not IF_WEBHOOK_URL:
            self.logger.info(f"MOCK DELIVERY {event_type} {aggregate_type} {aggregate_key}")
            return True

        try:
            response = self.send("", "POST", body)
        except Exception as error:  # noqa: BLE001 — qualquer falha de rede é "não entregue"
            self.logger.warning(f"delivery failed for event {event_id}: {error}")
            return False

        return 200 <= response.status < 300
