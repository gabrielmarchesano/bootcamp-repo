from uuid import uuid4

from tests.utils.random_generator import RandomGenerator


class PayloadGenerator:
    # ════════════════════════════════════════════════════════════════
    # Conta digital + microcrédito
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def create_customer_payload(
        person_type: str = "NATURAL",
        document: str = None,
        birth_date: str = "1990-05-17",
        annual_revenue: int = 12_000_000,
        is_pep: bool = None,
        legal_nature: str = None,
        owner_customer_id: str = None,
    ) -> dict:
        """Um cadastro de titular v7 válido.

        NATURAL leva CPF + birth_date; LEGAL leva CNPJ + legal_nature (e,
        quando EI, owner_customer_id apontando para a PF dona). Documentos
        saem só com dígitos — é o formato que a API de titular aceita.
        """
        payload = {
            "person_type": person_type,
            "name": "Maria da Silva",
            "annual_revenue": annual_revenue,
        }

        if person_type == "NATURAL":
            payload["document"] = document if document is not None else RandomGenerator.generate_cpf_digits()
            payload["birth_date"] = birth_date
            if is_pep is not None:
                payload["is_pep"] = is_pep
        else:
            payload["document"] = document if document is not None else RandomGenerator.generate_cnpj_digits()
            payload["legal_nature"] = legal_nature if legal_nature is not None else "LTDA"
            if owner_customer_id is not None:
                payload["owner_customer_id"] = owner_customer_id

        return payload

    @staticmethod
    def create_legal_customer_payload(
        legal_nature: str = "LTDA",
        document: str = None,
        annual_revenue: int = 12_000_000,
        owner_customer_id: str = None,
    ) -> dict:
        """Atalho para um titular LEGAL (SLU/LTDA/EI)."""
        return PayloadGenerator.create_customer_payload(
            person_type="LEGAL",
            document=document,
            annual_revenue=annual_revenue,
            legal_nature=legal_nature,
            owner_customer_id=owner_customer_id,
        )

    @staticmethod
    def create_credit_line_payload(
        total_limit: int = 2_000_000, monthly_interest_rate: float = 0.03, origination_fee_rate: float = 0.02
    ) -> dict:
        """Linha de microcrédito dentro da regra MPO (≤ R$ 21 mil, ≤ 4% a.m., TAC ≤ 3%)."""
        return {
            "total_limit": total_limit,
            "monthly_interest_rate": monthly_interest_rate,
            "origination_fee_rate": origination_fee_rate,
        }

    @staticmethod
    def create_loan_payload(amount: int = 500_000, installment_count: int = 6, purpose: str = "capital de giro") -> dict:
        return {
            "amount": amount,
            "installment_count": installment_count,
            "purpose": purpose,
            "sfn_debt_declaration": True,
        }

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
    def create_credit_wallet_payload(
        total_limit: int = 500_000, closing_day: int = 10, due_day: int = 20, autopay: bool = None
    ) -> dict:
        payload = {
            "total_limit": total_limit,
            "closing_day": closing_day,
            "due_day": due_day,
            "monthly_interest_rate": 0.08,
            "fine_rate": 0.02,
        }
        if autopay is not None:
            payload["autopay"] = autopay
        return payload

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
