from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from tests.utils.db_utils import DbUtils
from tests.utils.payload_generator import PayloadGenerator
from tests.utils.request_generator import RequestGenerator


def local_today() -> date:
    """Hoje no fuso das regras de negócio (o mesmo que a API usa)."""
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


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
    def create_credit_wallet(account_id: str, total_limit: int = 500_000, autopay: bool = None) -> dict:
        status, wallet = RequestGenerator.POST_credit_wallet(
            account_id, PayloadGenerator.create_credit_wallet_payload(total_limit=total_limit, autopay=autopay)
        )
        assert status == 201, wallet
        return wallet

    # ════════════════════════════════════════════════════════════════
    # Microcrédito
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def create_ei(owner_customer_id: str, initial_balance: int = 0) -> dict:
        """EI/MEI ACTIVE da PF `owner_customer_id`, com conta própria (mesmo patrimônio da PF)."""
        payload = PayloadGenerator.create_legal_customer_payload(legal_nature="EI", owner_customer_id=owner_customer_id)
        status, ei = RequestGenerator.POST_customer(payload)
        assert status == 201, ei
        assert ei["status"] == "ACTIVE", ei

        if initial_balance > 0:
            spi_payload = PayloadGenerator.create_spi_received_payload(ei["account_number"], initial_balance)
            status, incoming = RequestGenerator.POST_webhook_spi(spi_payload)
            assert status == 200, incoming
        return ei

    @staticmethod
    def create_credit_line(customer_id: str, **terms) -> dict:
        status, line = RequestGenerator.PUT_credit_line(customer_id, PayloadGenerator.create_credit_line_payload(**terms))
        assert status == 200, line
        return line

    @staticmethod
    def create_borrower(initial_balance: int = 0, person_type: str = "NATURAL", **line_terms) -> dict:
        """Titular com conta ACTIVE e linha de microcrédito do patrimônio."""
        customer = ObjectGenerator.create_active_account(person_type=person_type, initial_balance=initial_balance)
        ObjectGenerator.create_credit_line(customer["customer_id"], **line_terms)
        return customer

    @staticmethod
    def create_loan(account_id: str, amount: int = 500_000, installment_count: int = 6) -> dict:
        status, loan = RequestGenerator.POST_loan(
            account_id, PayloadGenerator.create_loan_payload(amount, installment_count), str(uuid4())
        )
        assert status == 201, loan
        return loan

    @staticmethod
    def credit_line_of(customer_id: str) -> dict:
        status, line = RequestGenerator.GET_credit_line(customer_id)
        assert status == 200, line
        return line

    @staticmethod
    def loan_of(loan_id: str) -> dict:
        status, loan = RequestGenerator.GET_loan(loan_id)
        assert status == 200, loan
        return loan

    @staticmethod
    def make_installments_due(loan_id: str, numbers, days_ago: int = 1) -> None:
        """Vence as parcelas `numbers` do contrato há `days_ago` dias, sem esperar o calendário."""
        DbUtils.execute(
            "UPDATE installment SET due_date = :due "
            "WHERE loan_id = (SELECT id FROM loan WHERE key = CAST(:loan AS uuid)) AND number = ANY(:numbers)",
            {"due": local_today() - timedelta(days=days_ago), "loan": loan_id, "numbers": list(numbers)},
        )

    # ════════════════════════════════════════════════════════════════
    # Cartão e fatura
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def create_credit_purchase(card_id: str, amount: int, installment_count: int = 1) -> str:
        """Compra no crédito autorizada e capturada: vira item na fatura. Devolve o authorization_id."""
        payload = PayloadGenerator.create_authorization_payload(card_id, amount, installment_count=installment_count)
        status, decision = RequestGenerator.POST_card_authorization(payload)
        assert status == 200 and decision["status"] == "APPROVED", decision

        capture = {"capture_id": f"cap-{uuid4().hex[:12]}", "authorization_id": payload["authorization_id"], "amount": amount}
        status, captured = RequestGenerator.POST_card_capture(capture)
        assert status == 200, captured
        return payload["authorization_id"]

    @staticmethod
    def open_invoice_of(wallet_id: str) -> dict:
        status, invoices = RequestGenerator.GET_wallet_invoices(wallet_id, {"status": "OPEN"})
        assert status == 200 and len(invoices["items"]) == 1, invoices
        return invoices["items"][0]

    @staticmethod
    def invoice_of(invoice_id: str) -> dict:
        status, invoice = RequestGenerator.GET_invoice(invoice_id)
        assert status == 200, invoice
        return invoice

    @staticmethod
    def move_invoice_dates(invoice_id: str, closing_days_ago: int, due_in_days: int) -> None:
        """Põe o fechamento e o vencimento relativos a hoje (o CHECK exige vencimento depois do fechamento)."""
        today = local_today()
        DbUtils.execute(
            "UPDATE invoice SET closing_date = :closing, due_date = :due WHERE key = CAST(:invoice AS uuid)",
            {
                "closing": today - timedelta(days=closing_days_ago),
                "due": today + timedelta(days=due_in_days),
                "invoice": invoice_id,
            },
        )

    @staticmethod
    def overdue_invoice(card_id: str, wallet_id: str, amount: int) -> dict:
        """Fatura com uma compra de `amount`, fechada e vencida ontem — status OVERDUE."""
        ObjectGenerator.create_credit_purchase(card_id, amount)
        invoice = ObjectGenerator.open_invoice_of(wallet_id)

        ObjectGenerator.move_invoice_dates(invoice["invoice_id"], closing_days_ago=3, due_in_days=5)
        ObjectGenerator.run_job("close_invoices")
        ObjectGenerator.move_invoice_dates(invoice["invoice_id"], closing_days_ago=3, due_in_days=-1)
        ObjectGenerator.run_job("mark_overdue_invoices")

        invoice = ObjectGenerator.invoice_of(invoice["invoice_id"])
        assert invoice["status"] == "OVERDUE", invoice
        return invoice

    @staticmethod
    def expire_authorization_now(authorization_id: str) -> None:
        """Faz a autorização passar do prazo de captura agora."""
        DbUtils.execute(
            "UPDATE card_authorization SET expires_at = now() - interval '1 minute' WHERE authorization_id = :id",
            {"id": authorization_id},
        )

    @staticmethod
    def schedule_ted_for_today(transfer_id: str) -> None:
        """A TED agendada (a API só aceita dia útil futuro) passa a vencer hoje."""
        DbUtils.execute(
            "UPDATE transfer SET scheduled_for = :today WHERE key = CAST(:key AS uuid)",
            {"today": local_today(), "key": transfer_id},
        )

    @staticmethod
    def leave_transfer_without_answer(transfer_id: str, minutes: int) -> None:
        """A transferência SENT fica `minutes` sem retorno do trilho."""
        DbUtils.execute(
            "UPDATE transfer SET updated_at = now() - make_interval(mins => :minutes) WHERE key = CAST(:key AS uuid)",
            {"minutes": minutes, "key": transfer_id},
        )

    # ════════════════════════════════════════════════════════════════
    # Jobs
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def run_job(job_name: str) -> dict:
        status, body = RequestGenerator.POST_job(job_name)
        assert status == 200, body
        return body["result"]

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