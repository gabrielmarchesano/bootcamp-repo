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
