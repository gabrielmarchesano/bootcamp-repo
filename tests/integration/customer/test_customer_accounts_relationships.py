from tests.utils import PayloadGenerator, RequestGenerator


class TestAdditionalAccounts:
    def test_opens_additional_account_and_lists_both(self):
        _, created = RequestGenerator.POST_customer(PayloadGenerator.create_customer_payload())
        customer_id = created["customer_id"]

        status, extra = RequestGenerator.POST_customer_account(customer_id)
        assert status == 201, extra
        assert extra["status"] == "ACTIVE"
        assert extra["account_id"] != created["account_id"]

        status, listed = RequestGenerator.GET_customer_accounts(customer_id)
        assert status == 200
        ids = [item["account_id"] for item in listed["items"]]
        assert created["account_id"] in ids
        assert extra["account_id"] in ids
        # ordenação determinística por created_at: a conta de criação vem primeiro.
        assert ids[0] == created["account_id"]

    def test_additional_account_refused_when_holder_not_approved(self):
        """Titular com conta REJECTED (KYC rejeitado) não abre conta adicional (QIT001051)."""
        payload = PayloadGenerator.create_customer_payload(document="52998224725")
        status, created = RequestGenerator.POST_customer(payload)
        if status == 409:
            return  # CPF da lista restritiva já cadastrado por outro teste

        assert created["status"] == "REJECTED"

        status, error = RequestGenerator.POST_customer_account(created["customer_id"])
        assert status == 422
        assert error["code"] == "QIT001051"

    def test_accounts_of_unknown_customer_is_404(self):
        status, error = RequestGenerator.GET_customer_accounts("00000000-0000-0000-0000-000000000000")
        assert status == 404
        assert error["code"] == "QIT001008"


class TestRelationships:
    def test_creates_partner_relationship_between_legal_and_natural(self):
        _, pf = RequestGenerator.POST_customer(PayloadGenerator.create_customer_payload())
        _, pj = RequestGenerator.POST_customer(PayloadGenerator.create_legal_customer_payload(legal_nature="LTDA"))

        status, relationship = RequestGenerator.POST_customer_relationship(
            pj["customer_id"], {"natural_customer_id": pf["customer_id"], "role": "PARTNER"}
        )
        assert status == 201, relationship
        assert relationship["role"] == "PARTNER"
        assert relationship["legal_customer_id"] == pj["customer_id"]
        assert relationship["natural_customer_id"] == pf["customer_id"]

    def test_duplicate_relationship_is_422(self):
        _, pf = RequestGenerator.POST_customer(PayloadGenerator.create_customer_payload())
        _, pj = RequestGenerator.POST_customer(PayloadGenerator.create_legal_customer_payload(legal_nature="LTDA"))
        body = {"natural_customer_id": pf["customer_id"], "role": "ADMINISTRATOR"}

        status, _ = RequestGenerator.POST_customer_relationship(pj["customer_id"], body)
        assert status == 201

        status, error = RequestGenerator.POST_customer_relationship(pj["customer_id"], body)
        assert status == 422
        assert error["code"] == "QIT001052"

    def test_legal_path_must_be_legal_and_related_must_be_natural(self):
        _, pf = RequestGenerator.POST_customer(PayloadGenerator.create_customer_payload())
        _, pj = RequestGenerator.POST_customer(PayloadGenerator.create_legal_customer_payload(legal_nature="LTDA"))

        # path é PF (NATURAL): não pode ser o lado legal.
        status, error = RequestGenerator.POST_customer_relationship(
            pf["customer_id"], {"natural_customer_id": pf["customer_id"], "role": "ATTORNEY"}
        )
        assert status == 422
        assert error["code"] == "QIT001052"

        # related é PJ (LEGAL): não pode ser o lado natural.
        status, error = RequestGenerator.POST_customer_relationship(
            pj["customer_id"], {"natural_customer_id": pj["customer_id"], "role": "ATTORNEY"}
        )
        assert status == 422
        assert error["code"] == "QIT001052"
