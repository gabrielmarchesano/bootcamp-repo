from tests.utils import PayloadGenerator, RequestGenerator


class TestCustomerGetUpdate:
    def test_get_returns_customer_with_account(self):
        payload = PayloadGenerator.create_legal_customer_payload(legal_nature="LTDA")
        _, created = RequestGenerator.POST_customer(payload)

        status, customer = RequestGenerator.GET_customer(created["customer_id"])

        assert status == 200
        assert customer["person_type"] == "LEGAL"
        assert customer["document"] == payload["document"]
        assert customer["legal_nature"] == "LTDA"
        assert customer["account_id"] == created["account_id"]
        assert customer["kyc_status"] == "APPROVED"

    def test_unknown_or_malformed_id_is_404(self):
        for customer_id in ("00000000-0000-0000-0000-000000000000", "nao-e-um-uuid"):
            status, response = RequestGenerator.GET_customer(customer_id)
            assert status == 404, customer_id
            assert response["code"] == "QIT001008"

    def test_patch_revenue_recalculates_eligibility(self):
        payload = PayloadGenerator.create_customer_payload(annual_revenue=10_000_000)
        _, created = RequestGenerator.POST_customer(payload)
        assert created["microcredit_eligible"] is True

        status, customer = RequestGenerator.PATCH_customer(created["customer_id"], {"annual_revenue": 50_000_000})
        assert status == 200
        assert customer["microcredit_eligible"] is False

        status, customer = RequestGenerator.PATCH_customer(created["customer_id"], {"annual_revenue": 30_000_000})
        assert status == 200
        assert customer["microcredit_eligible"] is True
