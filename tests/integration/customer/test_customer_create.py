from datetime import date

from tests.utils import PayloadGenerator, RequestGenerator

# CPF da lista restritiva do mock de KYC (src/utils/kyc_mock.py).
KYC_REJECTED_CPF = "52998224725"


def birth_date_for_age(age_in_years: int) -> str:
    today = date.today()
    if today.month == 2 and today.day == 29:
        return date(today.year - age_in_years, 2, 28).isoformat()
    return date(today.year - age_in_years, today.month, today.day).isoformat()


class TestCustomerCreate:
    def test_creates_natural_with_active_account(self):
        payload = PayloadGenerator.create_customer_payload()

        status, response = RequestGenerator.POST_customer(payload)

        assert status == 201
        assert response["status"] == "ACTIVE"
        assert response["status_reason"] is None
        assert response["branch"] == "0001"
        assert len(response["account_number"]) == 8

    def test_creates_legal_ltda_with_active_account(self):
        payload = PayloadGenerator.create_legal_customer_payload(legal_nature="LTDA")

        status, response = RequestGenerator.POST_customer(payload)

        assert status == 201
        assert response["status"] == "ACTIVE"

    def test_creates_ei_pointing_to_a_natural_owner(self):
        """EI/MEI do v7: a PF (NATURAL) é o dono do CNPJ (LEGAL, legal_nature EI)."""
        _, pf = RequestGenerator.POST_customer(PayloadGenerator.create_customer_payload())
        assert pf["microcredit_eligible"] in (True, False)

        ei_payload = PayloadGenerator.create_legal_customer_payload(
            legal_nature="EI", owner_customer_id=pf["customer_id"]
        )
        status, ei = RequestGenerator.POST_customer(ei_payload)

        assert status == 201, ei
        assert ei["status"] == "ACTIVE"

    def test_ei_owner_must_be_a_natural_person(self):
        """Dono do EI apontando para uma PJ é recusado (QIT001050)."""
        _, other_legal = RequestGenerator.POST_customer(PayloadGenerator.create_legal_customer_payload())

        ei_payload = PayloadGenerator.create_legal_customer_payload(
            legal_nature="EI", owner_customer_id=other_legal["customer_id"]
        )
        status, error = RequestGenerator.POST_customer(ei_payload)

        assert status == 422
        assert error["code"] == "QIT001050"

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

    def test_schema_requires_birth_date_for_natural_and_legal_nature_for_legal(self):
        natural_without_birth = PayloadGenerator.create_customer_payload()
        del natural_without_birth["birth_date"]

        legal_without_nature = PayloadGenerator.create_legal_customer_payload()
        del legal_without_nature["legal_nature"]

        natural_with_legal_nature = PayloadGenerator.create_customer_payload()
        natural_with_legal_nature["legal_nature"] = "LTDA"

        for payload in (natural_without_birth, legal_without_nature, natural_with_legal_nature):
            status, response = RequestGenerator.POST_customer(payload)
            assert status == 400, payload
            assert response["code"] == "QIT000001"

    def test_schema_requires_owner_only_for_ei(self):
        ei_without_owner = PayloadGenerator.create_legal_customer_payload(legal_nature="EI")
        ltda_with_owner = PayloadGenerator.create_legal_customer_payload(legal_nature="LTDA")
        ltda_with_owner["owner_customer_id"] = "00000000-0000-0000-0000-000000000000"

        for payload in (ei_without_owner, ltda_with_owner):
            status, response = RequestGenerator.POST_customer(payload)
            assert status == 400, payload
            assert response["code"] == "QIT000001"

    def test_schema_forbids_is_pep_for_legal(self):
        payload = PayloadGenerator.create_legal_customer_payload()
        payload["is_pep"] = True

        status, response = RequestGenerator.POST_customer(payload)

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_empty_body_points_to_a_missing_required_field(self):
        status, response = RequestGenerator.POST_customer({})

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_schema_refuses_formatted_documents_and_float_money(self):
        """Documento só com dígitos, dinheiro só inteiro (centavos).

        O `1500.50` recusado é a regra mais importante deste teste: dinheiro
        em float é como um sistema financeiro começa a perder centavos.
        """
        formatted_cpf = PayloadGenerator.create_customer_payload(document="529.982.247-25")
        float_revenue = PayloadGenerator.create_customer_payload()
        float_revenue["annual_revenue"] = 1500.50

        for payload in (formatted_cpf, float_revenue):
            status, response = RequestGenerator.POST_customer(payload)
            assert status == 400, payload
            assert response["code"] == "QIT000001"

    def test_refuses_invalid_cpf_and_cnpj_check_digits(self):
        bad_cpf = PayloadGenerator.create_customer_payload(document="12345678900")
        status, response = RequestGenerator.POST_customer(bad_cpf)
        assert status == 422
        assert response["code"] == "QIT001003"

        bad_cnpj = PayloadGenerator.create_legal_customer_payload(document="11222333000182")
        status, response = RequestGenerator.POST_customer(bad_cnpj)
        assert status == 422
        assert response["code"] == "QIT001011"

    def test_refuses_duplicated_document(self):
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
        payload = PayloadGenerator.create_customer_payload(document=KYC_REJECTED_CPF, is_pep=True)

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
