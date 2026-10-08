from os import environ

from tests.utils.requisition import ClientRequisition


INTERNAL_TOKEN = environ.get("INTERNAL_TOKEN", "default_token")


class RequestGenerator:
    """Um método por rota do src/app.py, com o caminho escrito igual ao de lá."""

    @staticmethod
    def _send(method: str, endpoint: str, payload: dict = None, idempotency_key: str = None, params: dict = None):
        headers = {"INTERNAL-TOKEN": INTERNAL_TOKEN}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        response = ClientRequisition.send(method, endpoint, payload=payload, headers=headers, query_params=params)
        return response.response_status, response.response_json

    # ════════════════════════════════════════════════════════════════
    # A · Titulares e contas
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def POST_customer(payload: dict):
        return RequestGenerator._send("POST", "/customer", payload)

    @staticmethod
    def GET_customer(customer_id: str):
        return RequestGenerator._send("GET", f"/customer/{customer_id}")

    @staticmethod
    def PATCH_customer(customer_id: str, payload: dict):
        return RequestGenerator._send("PATCH", f"/customer/{customer_id}", payload)

    @staticmethod
    def POST_customer_account(customer_id: str):
        return RequestGenerator._send("POST", f"/customer/{customer_id}/account")

    @staticmethod
    def GET_customer_accounts(customer_id: str):
        return RequestGenerator._send("GET", f"/customer/{customer_id}/account")

    @staticmethod
    def POST_customer_relationship(customer_id: str, payload: dict):
        return RequestGenerator._send("POST", f"/customer/{customer_id}/relationship", payload)

    @staticmethod
    def GET_account(account_id: str):
        return RequestGenerator._send("GET", f"/account/{account_id}")

    @staticmethod
    def PATCH_account_status(account_id: str, status: str, reason: str = "teste automatizado"):
        return RequestGenerator._send("PATCH", f"/account/{account_id}/status", {"status": status, "reason": reason})

    @staticmethod
    def GET_statement(account_id: str, params: dict = None):
        return RequestGenerator._send("GET", f"/account/{account_id}/statement", params=params)

    @staticmethod
    def GET_account_transfers(account_id: str, params: dict = None):
        return RequestGenerator._send("GET", f"/account/{account_id}/transfer", params=params)

    # ════════════════════════════════════════════════════════════════
    # B · Microcrédito
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def PUT_credit_line(customer_id: str, payload: dict):
        return RequestGenerator._send("PUT", f"/customer/{customer_id}/credit_line", payload)

    @staticmethod
    def GET_credit_line(customer_id: str):
        return RequestGenerator._send("GET", f"/customer/{customer_id}/credit_line")

    @staticmethod
    def POST_loan_simulation(account_id: str, payload: dict):
        return RequestGenerator._send("POST", f"/account/{account_id}/loan/simulation", payload)

    @staticmethod
    def POST_loan(account_id: str, payload: dict, idempotency_key: str = None):
        return RequestGenerator._send("POST", f"/account/{account_id}/loan", payload, idempotency_key)

    @staticmethod
    def GET_account_loans(account_id: str, params: dict = None):
        return RequestGenerator._send("GET", f"/account/{account_id}/loan", params=params)

    @staticmethod
    def GET_loan(loan_id: str):
        return RequestGenerator._send("GET", f"/loan/{loan_id}")

    @staticmethod
    def POST_loan_payment(loan_id: str, payload: dict, idempotency_key: str = None):
        return RequestGenerator._send("POST", f"/loan/{loan_id}/payment", payload, idempotency_key)

    # ════════════════════════════════════════════════════════════════
    # C · Transferências, Pix, TED e webhooks dos trilhos
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def POST_transfer(payload: dict, idempotency_key: str = None):
        return RequestGenerator._send("POST", "/transfer", payload, idempotency_key)

    @staticmethod
    def GET_transfer(transfer_id: str):
        return RequestGenerator._send("GET", f"/transfer/{transfer_id}")

    @staticmethod
    def PATCH_transfer_cancel(transfer_id: str):
        return RequestGenerator._send("PATCH", f"/transfer/{transfer_id}/cancel")

    @staticmethod
    def POST_webhook_spi(payload: dict):
        return RequestGenerator._send("POST", "/webhook/spi", payload)

    @staticmethod
    def POST_webhook_str(payload: dict):
        return RequestGenerator._send("POST", "/webhook/str", payload)

    @staticmethod
    def POST_pix_key(account_id: str, payload: dict):
        return RequestGenerator._send("POST", f"/account/{account_id}/pix_key", payload)

    @staticmethod
    def GET_pix_keys(account_id: str):
        return RequestGenerator._send("GET", f"/account/{account_id}/pix_key")

    @staticmethod
    def DELETE_pix_key(account_id: str, pix_key_id: str):
        return RequestGenerator._send("DELETE", f"/account/{account_id}/pix_key/{pix_key_id}")

    @staticmethod
    def GET_pix_key_lookup(pix_key: str, account_id: str):
        return RequestGenerator._send("GET", f"/pix_key/{pix_key}", params={"account_id": account_id})

    @staticmethod
    def POST_pix_transfer(account_id: str, payload: dict, idempotency_key: str):
        return RequestGenerator._send("POST", f"/account/{account_id}/pix_transfer", payload, idempotency_key)

    @staticmethod
    def POST_pix_reversal(account_id: str, incoming_transfer_id: str, payload: dict, idempotency_key: str):
        endpoint = f"/account/{account_id}/incoming_transfer/{incoming_transfer_id}/reversal"
        return RequestGenerator._send("POST", endpoint, payload, idempotency_key)

    @staticmethod
    def POST_ted_transfer(account_id: str, payload: dict, idempotency_key: str):
        return RequestGenerator._send("POST", f"/account/{account_id}/ted_transfer", payload, idempotency_key)

    # ════════════════════════════════════════════════════════════════
    # D · Carteira, cartões, faturas e rede
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def POST_credit_wallet(account_id: str, payload: dict):
        return RequestGenerator._send("POST", f"/account/{account_id}/credit_wallet", payload)

    @staticmethod
    def GET_credit_wallet(wallet_id: str):
        return RequestGenerator._send("GET", f"/credit_wallet/{wallet_id}")

    @staticmethod
    def PATCH_credit_wallet_limit(wallet_id: str, total_limit: int):
        return RequestGenerator._send("PATCH", f"/credit_wallet/{wallet_id}/limit", {"total_limit": total_limit})

    @staticmethod
    def PATCH_credit_wallet_status(wallet_id: str, status: str, reason: str = "teste automatizado"):
        return RequestGenerator._send("PATCH", f"/credit_wallet/{wallet_id}/status", {"status": status, "reason": reason})

    @staticmethod
    def GET_wallet_invoices(wallet_id: str, params: dict = None):
        return RequestGenerator._send("GET", f"/credit_wallet/{wallet_id}/invoice", params=params)

    @staticmethod
    def GET_invoice(invoice_id: str):
        return RequestGenerator._send("GET", f"/invoice/{invoice_id}")

    @staticmethod
    def POST_invoice_payment(invoice_id: str, payload: dict, idempotency_key: str = None):
        return RequestGenerator._send("POST", f"/invoice/{invoice_id}/payment", payload, idempotency_key)

    @staticmethod
    def POST_invoice_charge(invoice_id: str, payload: dict, idempotency_key: str = None):
        return RequestGenerator._send("POST", f"/invoice/{invoice_id}/charge", payload, idempotency_key)

    @staticmethod
    def POST_card(account_id: str, payload: dict):
        return RequestGenerator._send("POST", f"/account/{account_id}/card", payload)

    @staticmethod
    def GET_cards(account_id: str):
        return RequestGenerator._send("GET", f"/account/{account_id}/card")

    @staticmethod
    def GET_card(card_id: str):
        return RequestGenerator._send("GET", f"/card/{card_id}")

    @staticmethod
    def PATCH_card_activate(card_id: str, code: str):
        return RequestGenerator._send("PATCH", f"/card/{card_id}/activate", {"code": code})

    @staticmethod
    def PATCH_card_status(card_id: str, status: str, reason: str = "teste automatizado"):
        return RequestGenerator._send("PATCH", f"/card/{card_id}/status", {"status": status, "reason": reason})

    @staticmethod
    def POST_card_authorization(payload: dict):
        return RequestGenerator._send("POST", "/card/authorization", payload)

    @staticmethod
    def GET_card_authorization(authorization_id: str):
        return RequestGenerator._send("GET", f"/card/authorization/{authorization_id}")

    @staticmethod
    def POST_card_increment(authorization_id: str, payload: dict):
        return RequestGenerator._send("POST", f"/card/authorization/{authorization_id}/increment", payload)

    @staticmethod
    def POST_card_reversal(authorization_id: str, payload: dict):
        return RequestGenerator._send("POST", f"/card/authorization/{authorization_id}/reversal", payload)

    @staticmethod
    def POST_card_capture(payload: dict):
        return RequestGenerator._send("POST", "/card/captures", payload)

    @staticmethod
    def POST_card_refund(payload: dict):
        return RequestGenerator._send("POST", "/card/refunds", payload)

    # ════════════════════════════════════════════════════════════════
    # E · Jobs
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def POST_job(job_name: str):
        return RequestGenerator._send("POST", f"/job/{job_name}")
