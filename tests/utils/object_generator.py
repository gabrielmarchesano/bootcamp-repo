from tests.utils.payload_generator import PayloadGenerator
from tests.utils.request_generator import RequestGenerator


class ObjectGenerator:
    # ════════════════════════════════════════════════════════════════
    # Conta digital + microcrédito
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def create_active_account(person_type: str = "NATURAL", initial_balance: int = 0) -> dict:
        """Cliente novo com conta ACTIVE e, se pedido, saldo inicial via PIX recebido.

        O saldo entra pelo webhook do SPI — o mesmo caminho do dinheiro de
        verdade. Não existe atalho de "depósito" na API, e o teste não
        inventa um.
        """
        payload = PayloadGenerator.create_customer_payload(person_type=person_type)

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

    @staticmethod
    def create_credit_wallet(account_id: str, total_limit: int = 500_000) -> dict:
        status, wallet = RequestGenerator.POST_credit_wallet(
            account_id, PayloadGenerator.create_credit_wallet_payload(total_limit=total_limit)
        )
        assert status == 201, wallet
        return wallet

    @staticmethod
    def create_card(account_id: str, card_type: str = "VIRTUAL", functions: str = "MULTIPLE") -> dict:
        status, card = RequestGenerator.POST_card(account_id, PayloadGenerator.create_card_payload(card_type, functions))
        assert status == 201, card
        return card

    @staticmethod
    def own_pix_key(account_id: str, email: str) -> dict:
        status, pix_key = RequestGenerator.POST_pix_key(account_id, {"key_type": "EMAIL", "key_value": email})
        assert status == 201, pix_key
        return pix_key

    @staticmethod
    def lookup(pix_key: str, account_id: str) -> dict:
        status, inquiry = RequestGenerator.GET_pix_key_lookup(pix_key, account_id)
        assert status == 200, inquiry
        return inquiry