from uuid import uuid4

from tests.utils.random_generator import RandomGenerator


class PayloadGenerator:
    @staticmethod
    def create_sample_entity_payload(
        hello: str = None,
        name: str = None,
        email: str = None,
        document_number: str = None,
        birthdate: str = None,
    ) -> dict:
        """Um cadastro valido, com qualquer campo trocado a pedido.

        Sem argumento nenhum o payload sai aleatorio no que precisa ser
        unico (e-mail e CPF), pra que dois cadastros seguidos nao batam
        na regra de duplicidade. Quem testa FILTRO precisa do contrario
        disso: um valor conhecido, pra poder procurar por ele depois.
        """
        if hello is None:
            hello = "world"

        if name is None:
            name = "Maria da Silva"

        if email is None:
            email = f"maria.silva.{uuid4()}@exemplo.com.br"

        if document_number is None:
            document_number = RandomGenerator.generate_cpf()

        if birthdate is None:
            birthdate = "1990-05-17"

        payload = {
            "hello": hello,
            "name": name,
            "email": email,
            "document_number": document_number,
            "birthdate": birthdate,
        }
        return payload

    @staticmethod
    def create_new_status_payload(new_status: str = None) -> dict:
        payload = {"status": new_status}
        return payload

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
        aceita (diferente do sample_entity, que usa pontos e traço).
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
