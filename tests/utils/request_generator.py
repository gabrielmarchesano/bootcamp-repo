from os import environ

from tests.utils.requisition import ClientRequisition


INTERNAL_TOKEN = environ.get("INTERNAL_TOKEN", "default_token")


class RequestGenerator:
    # ════════════════════════════════════════════════════════════════
    # Conta digital + microcrédito
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def POST_customer(payload: dict):
        response = ClientRequisition.send(
            "POST", "/customers", payload=payload, headers={"INTERNAL-TOKEN": INTERNAL_TOKEN}
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_customer(customer_id: str):
        response = ClientRequisition.send(
            "GET", f"/customers/{customer_id}", headers={"INTERNAL-TOKEN": INTERNAL_TOKEN}
        )
        return response.response_status, response.response_json

    @staticmethod
    def PATCH_customer(customer_id: str, payload: dict):
        response = ClientRequisition.send(
            "PATCH", f"/customers/{customer_id}", payload=payload, headers={"INTERNAL-TOKEN": INTERNAL_TOKEN}
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_account(account_id: str):
        response = ClientRequisition.send(
            "GET", f"/accounts/{account_id}", headers={"INTERNAL-TOKEN": INTERNAL_TOKEN}
        )
        return response.response_status, response.response_json

    @staticmethod
    def PATCH_account_status(account_id: str, status: str, reason: str = "teste automatizado"):
        response = ClientRequisition.send(
            "PATCH",
            f"/accounts/{account_id}/status",
            payload={"status": status, "reason": reason},
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_statement(account_id: str, params: dict = None):
        response = ClientRequisition.send(
            "GET",
            f"/accounts/{account_id}/statement",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
            query_params=params,
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_account_transfers(account_id: str, params: dict = None):
        response = ClientRequisition.send(
            "GET",
            f"/accounts/{account_id}/transfers",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
            query_params=params,
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_transfer(payload: dict, idempotency_key: str = None):
        headers = {"INTERNAL-TOKEN": INTERNAL_TOKEN}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        response = ClientRequisition.send("POST", "/transfers", payload=payload, headers=headers)
        return response.response_status, response.response_json

    @staticmethod
    def GET_transfer(transfer_id: str):
        response = ClientRequisition.send(
            "GET", f"/transfers/{transfer_id}", headers={"INTERNAL-TOKEN": INTERNAL_TOKEN}
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_webhook_spi(payload: dict):
        response = ClientRequisition.send(
            "POST", "/webhooks/spi", payload=payload, headers={"INTERNAL-TOKEN": INTERNAL_TOKEN}
        )
        return response.response_status, response.response_json

    # ════════════════════════════════════════════════════════════════
    # Pix, TED e webhooks dos trilhos (sprint 2b)
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def _send(method: str, endpoint: str, payload: dict = None, idempotency_key: str = None, params: dict = None):
        headers = {"INTERNAL-TOKEN": INTERNAL_TOKEN}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        response = ClientRequisition.send(method, endpoint, payload=payload, headers=headers, query_params=params)
        return response.response_status, response.response_json

    @staticmethod
    def POST_pix_key(account_id: str, payload: dict):
        return RequestGenerator._send("POST", f"/accounts/{account_id}/pix_keys", payload)

    @staticmethod
    def GET_pix_keys(account_id: str):
        return RequestGenerator._send("GET", f"/accounts/{account_id}/pix_keys")

    @staticmethod
    def DELETE_pix_key(account_id: str, pix_key_id: str):
        return RequestGenerator._send("DELETE", f"/accounts/{account_id}/pix_keys/{pix_key_id}")

    @staticmethod
    def GET_pix_key_lookup(pix_key: str, account_id: str):
        return RequestGenerator._send("GET", f"/pix_keys/{pix_key}", params={"account_id": account_id})

    @staticmethod
    def POST_pix_transfer(account_id: str, payload: dict, idempotency_key: str):
        return RequestGenerator._send("POST", f"/accounts/{account_id}/pix_transfers", payload, idempotency_key)

    @staticmethod
    def POST_pix_reversal(account_id: str, incoming_transfer_id: str, payload: dict, idempotency_key: str):
        endpoint = f"/accounts/{account_id}/incoming_transfers/{incoming_transfer_id}/reversals"
        return RequestGenerator._send("POST", endpoint, payload, idempotency_key)

    @staticmethod
    def POST_ted_transfer(account_id: str, payload: dict, idempotency_key: str):
        return RequestGenerator._send("POST", f"/accounts/{account_id}/ted_transfers", payload, idempotency_key)

    @staticmethod
    def PATCH_transfer_cancel(transfer_id: str):
        return RequestGenerator._send("PATCH", f"/transfers/{transfer_id}/cancel")

    @staticmethod
    def POST_webhook_str(payload: dict):
        return RequestGenerator._send("POST", "/webhooks/str", payload)

    # ════════════════════════════════════════════════════════════════
    # Carteira, cartões e rede (sprint 4)
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def POST_credit_wallet(account_id: str, payload: dict):
        return RequestGenerator._send("POST", f"/accounts/{account_id}/credit_wallets", payload)

    @staticmethod
    def GET_credit_wallet(wallet_id: str):
        return RequestGenerator._send("GET", f"/credit_wallets/{wallet_id}")

    @staticmethod
    def PATCH_credit_wallet_limit(wallet_id: str, total_limit: int):
        return RequestGenerator._send("PATCH", f"/credit_wallets/{wallet_id}/limit", {"total_limit": total_limit})

    @staticmethod
    def PATCH_credit_wallet_status(wallet_id: str, status: str, reason: str = "teste automatizado"):
        return RequestGenerator._send("PATCH", f"/credit_wallets/{wallet_id}/status", {"status": status, "reason": reason})

    @staticmethod
    def GET_wallet_invoices(wallet_id: str, params: dict = None):
        return RequestGenerator._send("GET", f"/credit_wallets/{wallet_id}/invoices", params=params)

    @staticmethod
    def GET_invoice(invoice_id: str):
        return RequestGenerator._send("GET", f"/invoices/{invoice_id}")

    @staticmethod
    def POST_card(account_id: str, payload: dict):
        return RequestGenerator._send("POST", f"/accounts/{account_id}/cards", payload)

    @staticmethod
    def GET_card(card_id: str):
        return RequestGenerator._send("GET", f"/cards/{card_id}")

    @staticmethod
    def PATCH_card_activate(card_id: str, code: str):
        return RequestGenerator._send("PATCH", f"/cards/{card_id}/activate", {"code": code})

    @staticmethod
    def PATCH_card_status(card_id: str, status: str, reason: str = "teste automatizado"):
        return RequestGenerator._send("PATCH", f"/cards/{card_id}/status", {"status": status, "reason": reason})

    @staticmethod
    def POST_card_authorization(payload: dict):
        return RequestGenerator._send("POST", "/cards/authorizations", payload)

    @staticmethod
    def GET_card_authorization(authorization_id: str):
        return RequestGenerator._send("GET", f"/cards/authorizations/{authorization_id}")

    @staticmethod
    def POST_card_increment(authorization_id: str, payload: dict):
        return RequestGenerator._send("POST", f"/cards/authorizations/{authorization_id}/increments", payload)

    @staticmethod
    def POST_card_reversal(authorization_id: str, payload: dict):
        return RequestGenerator._send("POST", f"/cards/authorizations/{authorization_id}/reversals", payload)

    @staticmethod
    def POST_card_capture(payload: dict):
        return RequestGenerator._send("POST", "/cards/captures", payload)

    @staticmethod
    def POST_card_refund(payload: dict):
        return RequestGenerator._send("POST", "/cards/refunds", payload)