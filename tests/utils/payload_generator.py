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

    # ════════════════════════════════════════════════════════════════
    # Pix, TED e cartões
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def target_account(ispb: str = "60746948", document: str = "32402502000135") -> dict:
        return {
            "ispb": ispb,
            "branch": "0452",
            "number": "370158",
            "digit": "1",
            "document": document,
            "name": "Fornecedor Externo LTDA",
            "account_type": "CHECKING",
        }

    @staticmethod
    def create_pix_key_payload(pix_key: str, end_to_end_id: str, amount: int, pix_message: str = None) -> dict:
        payload = {"pix_transfer_type": "KEY", "pix_key": pix_key, "end_to_end_id": end_to_end_id, "amount": amount}
        if pix_message is not None:
            payload["pix_message"] = pix_message
        return payload

    @staticmethod
    def create_pix_manual_payload(amount: int, target_account: dict = None) -> dict:
        return {
            "pix_transfer_type": "MANUAL",
            "target_account": target_account or PayloadGenerator.target_account(),
            "amount": amount,
        }

    @staticmethod
    def create_ted_payload(amount: int, schedule_date: str = None) -> dict:
        payload = {"target_account": PayloadGenerator.target_account(), "amount": amount}
        if schedule_date is not None:
            payload["schedule_date"] = schedule_date
        return payload

    @staticmethod
    def create_spi_event_payload(event: str, end_to_end_id: str, error_code: str = None) -> dict:
        payload = {"event": event, "end_to_end_id": end_to_end_id}
        if error_code is not None:
            payload["error_code"] = error_code
            payload["error_description"] = "Target account number is invalid."
        return payload

    @staticmethod
    def create_str_payload(event: str, **fields) -> dict:
        payload = {"event": event}
        payload.update(fields)
        return payload

    @staticmethod
    def create_credit_wallet_payload(total_limit: int = 500_000, closing_day: int = 10, due_day: int = 20) -> dict:
        return {
            "total_limit": total_limit,
            "closing_day": closing_day,
            "due_day": due_day,
            "monthly_interest_rate": 0.08,
            "fine_rate": 0.02,
        }

    @staticmethod
    def create_card_payload(card_type: str = "VIRTUAL", functions: str = "MULTIPLE") -> dict:
        payload = {"type": card_type, "functions": functions, "printed_name": "MARIA DA SILVA", "card_name": "compras"}
        if card_type == "PLASTIC":
            payload["contactless_enabled"] = True
        return payload

    @staticmethod
    def create_authorization_payload(
        card_id: str, amount: int, function: str = "CREDIT", installment_count: int = 1, authorization_id: str = None
    ) -> dict:
        return {
            "authorization_id": authorization_id or f"auth-{uuid4().hex[:16]}",
            "card_id": card_id,
            "function": function,
            "amount": amount,
            "installment_count": installment_count,
            "merchant_name": "Mercado Teste",
            "mcc": "5411",
        }