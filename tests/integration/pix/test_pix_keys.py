from tests.utils import ObjectGenerator, RequestGenerator


def unique_email(prefix: str = "maria") -> str:
    from uuid import uuid4

    return f"{prefix}.{uuid4().hex[:10]}@exemplo.com"


class TestPixKeys:
    def test_register_list_and_delete(self):
        customer = ObjectGenerator.create_active_account()
        email = unique_email()

        status, key = RequestGenerator.POST_pix_key(customer["account_id"], {"key_type": "EMAIL", "key_value": email})
        assert status == 201, key
        assert key["status"] == "ACTIVE"

        _, listed = RequestGenerator.GET_pix_keys(customer["account_id"])
        assert [item["key_value"] for item in listed["items"]] == [email]

        status, deleted = RequestGenerator.DELETE_pix_key(customer["account_id"], key["pix_key_id"])
        assert status == 200
        assert deleted["status"] == "DELETED"

        _, listed = RequestGenerator.GET_pix_keys(customer["account_id"])
        assert listed["items"] == []

    def test_cpf_key_must_be_the_holders_own(self):
        customer = ObjectGenerator.create_active_account()

        status, own = RequestGenerator.POST_pix_key(customer["account_id"], {"key_type": "CPF", "key_value": customer_cpf(customer)})
        assert status == 201, own

        status, error = RequestGenerator.POST_pix_key(customer["account_id"], {"key_type": "CPF", "key_value": "52998224725"})
        assert status == 422
        assert error["code"] == "QIT001041"

    def test_evp_is_generated_by_the_api(self):
        customer = ObjectGenerator.create_active_account()

        status, key = RequestGenerator.POST_pix_key(customer["account_id"], {"key_type": "EVP"})

        assert status == 201
        assert len(key["key_value"]) == 36

    def test_same_key_cannot_live_in_two_accounts_but_can_be_reused_after_delete(self):
        first = ObjectGenerator.create_active_account()
        second = ObjectGenerator.create_active_account()
        email = unique_email()

        key = ObjectGenerator.own_pix_key(first["account_id"], email)
        status, error = RequestGenerator.POST_pix_key(second["account_id"], {"key_type": "EMAIL", "key_value": email})
        assert status == 409
        assert error["code"] == "QIT001029"

        RequestGenerator.DELETE_pix_key(first["account_id"], key["pix_key_id"])
        status, reborn = RequestGenerator.POST_pix_key(second["account_id"], {"key_type": "EMAIL", "key_value": email})
        assert status == 201, reborn

    def test_individual_has_at_most_five_keys(self):
        customer = ObjectGenerator.create_active_account()
        for _ in range(5):
            status, _ = RequestGenerator.POST_pix_key(customer["account_id"], {"key_type": "EVP"})
            assert status == 201

        status, error = RequestGenerator.POST_pix_key(customer["account_id"], {"key_type": "EVP"})

        assert status == 409
        assert error["code"] == "QIT001040"

    def test_dict_lookup_own_key_returns_masked_document_and_e2e(self):
        payer = ObjectGenerator.create_active_account()
        receiver = ObjectGenerator.create_active_account()
        email = unique_email()
        ObjectGenerator.own_pix_key(receiver["account_id"], email)

        inquiry = ObjectGenerator.lookup(email, payer["account_id"])

        assert inquiry["on_us"] is True
        assert inquiry["end_to_end_id"].startswith("E13370001")
        assert len(inquiry["end_to_end_id"]) == 32
        assert inquiry["owner_masked_document"].startswith("***.")
        assert inquiry["account_number"] == receiver["account_number"]

    def test_dict_lookup_external_mock_and_not_found(self):
        payer = ObjectGenerator.create_active_account()

        status, external = RequestGenerator.GET_pix_key_lookup("fornecedor@externo.com", payer["account_id"])
        assert status == 200
        assert external["on_us"] is False
        assert external["ispb"] == "60746948"

        status, error = RequestGenerator.GET_pix_key_lookup("ninguem@lugar-nenhum.com", payer["account_id"])
        assert status == 404
        assert error["code"] == "QIT001021"

    def test_lookup_requires_account_id(self):
        status, error = RequestGenerator._send("GET", "/pix_key/fornecedor@externo.com")

        assert status == 400
        assert error["code"] == "QIT000001"


def customer_cpf(customer: dict) -> str:
    _, full = RequestGenerator.GET_customer(customer["customer_id"])
    return full["document"]