from tests.utils.requisition import BaseConnectorResponse
from tests.utils.payload_generator import PayloadGenerator
from tests.utils.request_generator import RequestGenerator


class ObjectGenerator:
    @staticmethod
    def create_sample_entity(hello: str = None) -> BaseConnectorResponse:

        sample_entity_payload = PayloadGenerator.create_sample_entity_payload(hello=hello)

        status, response = RequestGenerator.POST_sample_entity(sample_entity_payload)
        assert status == 201

        return response

    @staticmethod
    def update_sample_entity(sample_entity_key, new_status: str = None) -> BaseConnectorResponse:

        sample_entity_payload = PayloadGenerator.create_new_status_payload(new_status)

        status, response = RequestGenerator.PUT_sample_entity(sample_entity_key, sample_entity_payload)
        assert status == 202

        return response

    # ════════════════════════════════════════════════════════════════
    # Conta digital + microcrédito
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def create_active_account(customer_type: str = "INDIVIDUAL", initial_balance: int = 0) -> dict:
        """Cliente novo com conta ACTIVE e, se pedido, saldo inicial via PIX recebido.

        O saldo entra pelo webhook do SPI — o mesmo caminho do dinheiro de
        verdade. Não existe atalho de "depósito" na API, e o teste não
        inventa um.
        """
        payload = PayloadGenerator.create_customer_payload(customer_type=customer_type)

        status, customer = RequestGenerator.POST_customer(payload)
        assert status == 201, customer
        assert customer["status"] == "ACTIVE", customer

        if initial_balance > 0:
            spi_payload = PayloadGenerator.create_spi_received_payload(customer["account_number"], initial_balance)
            status, incoming = RequestGenerator.POST_webhook_spi(spi_payload)
            assert status == 200, incoming
            assert incoming["status"] == "CREDITED", incoming

        return customer

    @staticmethod
    def balance_of(account_id: str) -> int:
        status, account = RequestGenerator.GET_account(account_id)
        assert status == 200, account
        return account["balance"]
