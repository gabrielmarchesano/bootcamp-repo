from uuid import uuid4

from tests.utils.random_generator import RandomGenerator


class PayloadGenerator:
    # ════════════════════════════════════════════════════════════════
    # Conta digital + microcrédito
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def create_customer_payload(
        customer_type: str = "INDIVIDUAL",
        cpf: str = None,
        cnpj: str = None,
        birth_date: str = "1990-05-17",
        annual_revenue: int = 12_000_000,
        is_pep: bool = None,
    ) -> dict:
        """Um cadastro válido. MEI ganha CNPJ sozinho; INDIVIDUAL fica sem.

        Documentos saem só com dígitos — é o formato que a API de cliente
        aceita.
        """
        if cpf is None:
            cpf = RandomGenerator.generate_cpf_digits()

        payload = {
            "cpf": cpf,
            "name": "Maria da Silva",
            "birth_date": birth_date,
            "type": customer_type,
            "annual_revenue": annual_revenue,
        }

        if customer_type == "MEI":
            payload["cnpj"] = cnpj if cnpj is not None else RandomGenerator.generate_cnpj_digits()

        if is_pep is not None:
            payload["is_pep"] = is_pep

        return payload

    @staticmethod
    def create_tef_payload(source_account_id: str, destination_account_id: str, amount: int) -> dict:
        return {
            "source_account_id": source_account_id,
            "method": "TEF",
            "amount": amount,
            "destination": {"account_id": destination_account_id},
        }

    @staticmethod
    def create_spi_received_payload(account_number: str, amount: int, external_id: str = None) -> dict:
        if external_id is None:
            external_id = "E" + uuid4().hex

        return {
            "event": "RECEIVED",
            "external_id": external_id,
            "amount": amount,
            "destination_account": {"branch": "0001", "number": account_number},
            "sender": {"name": "Pagador Externo", "document": "52998224725", "ispb": "00000000"},
        }
