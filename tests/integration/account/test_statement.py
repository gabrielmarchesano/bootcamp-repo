from uuid import uuid4

from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator


class TestStatement:
    def test_statement_pages_through_cursor_without_gaps_or_repeats(self):
        """7 lançamentos em páginas de 3: 3 + 3 + 1, sem buraco e sem repetição.

        E a prova de que o extrato fecha: ao percorrer do mais novo ao mais
        antigo, cada `balance_after` é o anterior menos o `amount` da linha
        anterior — a conta se refaz sozinha, linha a linha.
        """
        customer = ObjectGenerator.create_active_account()
        account_id = customer["account_id"]

        for amount in (100, 200, 300, 400, 500, 600, 700):
            spi = PayloadGenerator.create_spi_received_payload(customer["account_number"], amount)
            status, _ = RequestGenerator.POST_webhook_spi(spi)
            assert status == 200

        seen = []
        cursor = None
        pages = 0

        while True:
            params = {"limit": "3"}
            if cursor is not None:
                params["cursor"] = cursor

            status, page = RequestGenerator.GET_statement(account_id, params)
            assert status == 200

            seen.extend(page["items"])
            pages = pages + 1
            cursor = page["next_cursor"]
            if cursor is None:
                break

        assert pages == 3
        assert [item["amount"] for item in seen] == [700, 600, 500, 400, 300, 200, 100]
        assert len({item["entry_id"] for item in seen}) == 7

        assert seen[0]["balance_after"] == 2800
        for newer, older in zip(seen, seen[1:]):
            assert older["balance_after"] == newer["balance_after"] - newer["amount"]

    def test_statement_of_empty_account(self):
        customer = ObjectGenerator.create_active_account()

        status, page = RequestGenerator.GET_statement(customer["account_id"])

        assert status == 200
        assert page["items"] == []
        assert page["next_cursor"] is None
        assert page["balance"] == 0

    def test_tampered_cursor_is_400_not_500(self):
        customer = ObjectGenerator.create_active_account()

        status, response = RequestGenerator.GET_statement(customer["account_id"], {"cursor": "bm9wZQ"})

        assert status == 400
        assert response["code"] == "QIT000010"

    def test_unknown_query_param_is_refused(self):
        customer = ObjectGenerator.create_active_account()

        status, response = RequestGenerator.GET_statement(customer["account_id"], {"page": "1"})

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_unknown_account_is_404(self):
        status, response = RequestGenerator.GET_statement(str(uuid4()))

        assert status == 404
        assert response["code"] == "QIT001009"
