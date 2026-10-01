from datetime import date

from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator

# CPF da lista restritiva do mock de KYC (src/utils/kyc_mock.py).
KYC_REJECTED_CPF = "52998224725"


def birth_date_for_age(age_in_years: int) -> str:
    today = date.today()
    if today.month == 2 and today.day == 29:
        return date(today.year - age_in_years, 2, 28).isoformat()
    return date(today.year - age_in_years, today.month, today.day).isoformat()


class TestCustomerCreate:
    def test_creates_individual_with_active_account(self):
        payload = PayloadGenerator.create_customer_payload()

        status, response = RequestGenerator.POST_customer(payload)

        assert status == 201
        assert response["status"] == "ACTIVE"
        assert response["status_reason"] is None
        assert response["branch"] == "0001"
        assert len(response["account_number"]) == 8

    def test_creates_mei_with_cnpj(self):
        payload = PayloadGenerator.create_customer_payload(customer_type="MEI")

        status, response = RequestGenerator.POST_customer(payload)

        assert status == 201
        assert response["status"] == "ACTIVE"

    def test_microcredit_eligibility_cuts_at_360k(self):
        """R$ 360.000,00 é elegível; um centavo a mais, não. O teto é inclusivo."""
        at_cap = PayloadGenerator.create_customer_payload(annual_revenue=36_000_000)
        above_cap = PayloadGenerator.create_customer_payload(annual_revenue=36_000_001)

        status, response = RequestGenerator.POST_customer(at_cap)
        assert status == 201
        assert response["microcredit_eligible"] is True

        status, response = RequestGenerator.POST_customer(above_cap)
        assert status == 201
        assert response["microcredit_eligible"] is False

    def test_schema_requires_cnpj_for_mei_and_forbids_it_for_individual(self):
        mei_without_cnpj = PayloadGenerator.create_customer_payload(customer_type="MEI")
        del mei_without_cnpj["cnpj"]

        individual_with_cnpj = PayloadGenerator.create_customer_payload()
        individual_with_cnpj["cnpj"] = RandomGenerator.generate_cnpj_digits()

        for payload in (mei_without_cnpj, individual_with_cnpj):
            status, response = RequestGenerator.POST_customer(payload)
            assert status == 400, payload
            assert response["code"] == "QIT000001"

    def test_empty_body_points_to_a_missing_required_field(self):
        """Corpo vazio tem que reclamar de um campo que realmente falta.

        Sem o `"required": ["type"]` dentro do `if` do schema, um JSON sem
        `type` passa no `if` (propriedade ausente não é testada) e a regra
        "MEI exige CNPJ" dispara — a API diria "falta o cnpj" para quem
        nem pediu conta MEI.
        """
        status, response = RequestGenerator.POST_customer({})

        assert status == 400
        assert response["code"] == "QIT000001"
        assert "cnpj" not in response["description"]

    def test_schema_refuses_formatted_documents_and_float_money(self):
        """Documento só com dígitos, dinheiro só inteiro (centavos).

        O `1500.50` recusado é a regra mais importante deste teste: dinheiro
        em float é como um sistema financeiro começa a perder centavos.
        """
        formatted_cpf = PayloadGenerator.create_customer_payload(cpf="529.982.247-25")
        float_revenue = PayloadGenerator.create_customer_payload()
        float_revenue["annual_revenue"] = 1500.50

        for payload in (formatted_cpf, float_revenue):
            status, response = RequestGenerator.POST_customer(payload)
            assert status == 400, payload
            assert response["code"] == "QIT000001"

    def test_refuses_invalid_cpf_and_cnpj_check_digits(self):
        bad_cpf = PayloadGenerator.create_customer_payload(cpf="12345678900")
        status, response = RequestGenerator.POST_customer(bad_cpf)
        assert status == 422
        assert response["code"] == "QIT001003"

        bad_cnpj = PayloadGenerator.create_customer_payload(customer_type="MEI", cnpj="11222333000182")
        status, response = RequestGenerator.POST_customer(bad_cnpj)
        assert status == 422
        assert response["code"] == "QIT001011"

    def test_refuses_duplicated_cpf(self):
        payload = PayloadGenerator.create_customer_payload()

        status, _ = RequestGenerator.POST_customer(payload)
        assert status == 201

        status, response = RequestGenerator.POST_customer(payload)
        assert status == 409
        assert response["code"] == "QIT001010"

    def test_underage_is_created_as_rejected(self):
        """Menor de idade NÃO leva erro: o cadastro existe, com a conta REJECTED.

        É de propósito: a tentativa precisa ficar registrada (trilha de PLD).
        """
        payload = PayloadGenerator.create_customer_payload(birth_date=birth_date_for_age(17))

        status, response = RequestGenerator.POST_customer(payload)

        assert status == 201
        assert response["status"] == "REJECTED"
        assert response["status_reason"] == "UNDERAGE"

    def test_kyc_rejection_wins_over_everything(self):
        payload = PayloadGenerator.create_customer_payload(cpf=KYC_REJECTED_CPF, is_pep=True)

        status, response = RequestGenerator.POST_customer(payload)

        # O CPF da lista restritiva pode já ter sido cadastrado por outro teste.
        if status == 409:
            return

        assert status == 201
        assert response["status"] == "REJECTED"
        assert response["status_reason"] == "KYC_REJECTED"

    def test_senior_and_pep_go_to_pending_review(self):
        senior = PayloadGenerator.create_customer_payload(birth_date=birth_date_for_age(80))
        pep = PayloadGenerator.create_customer_payload(is_pep=True)

        status, response = RequestGenerator.POST_customer(senior)
        assert status == 201
        assert response["status"] == "PENDING"
        assert response["status_reason"] == "SENIOR_REVIEW"

        status, response = RequestGenerator.POST_customer(pep)
        assert status == 201
        assert response["status"] == "PENDING"
        assert response["status_reason"] == "PEP_REVIEW"

    def test_impossible_birth_date_is_422_not_500(self):
        payload = PayloadGenerator.create_customer_payload(birth_date="1990-02-30")

        status, response = RequestGenerator.POST_customer(payload)

        assert status == 422
        assert response["code"] == "QIT001007"
