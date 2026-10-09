from datetime import timedelta
from uuid import uuid4

import pytest

from tests.utils import ObjectGenerator, PayloadGenerator, RequestGenerator
from tests.utils.object_generator import local_today


def key() -> str:
    return str(uuid4())


class TestJobRoute:
    def test_every_job_answers_and_unknown_is_404(self):
        for job_name in (
            "expire_authorizations",
            "close_invoices",
            "mark_overdue_invoices",
            "run_invoice_autopay",
            "run_scheduled_teds",
            "reconcile_spi_str",
            "collect_installments",
            "dispatch_outbox_events",
        ):
            status, body = RequestGenerator.POST_job(job_name)
            assert status == 200, (job_name, body)
            assert body["job"] == job_name
            assert "processed" in body["result"]

        status, _ = RequestGenerator.POST_job("drop_everything")
        assert status == 404


class TestCollectInstallments:
    def test_collects_due_installments_and_is_idempotent(self):
        borrower = ObjectGenerator.create_borrower(initial_balance=100_000)
        loan = ObjectGenerator.create_loan(borrower["account_id"], 600_000, 6)
        first = loan["installments"][0]
        ObjectGenerator.make_installments_due(loan["loan_id"], [1])
        balance_before = ObjectGenerator.balance_of(borrower["account_id"])

        ObjectGenerator.run_job("collect_installments")
        ObjectGenerator.run_job("collect_installments")

        after = {item["number"]: item for item in ObjectGenerator.loan_of(loan["loan_id"])["installments"]}
        assert after[1]["status"] == "PAID"
        assert after[2]["paid_amount"] == 0, "parcela que não venceu não é cobrada"
        assert ObjectGenerator.balance_of(borrower["account_id"]) == balance_before - first["total_amount"]
        assert ObjectGenerator.loan_of(loan["loan_id"])["outstanding_principal"] == 600_000 - first["principal_amount"]

    def test_without_balance_debits_what_exists_and_marks_overdue(self):
        borrower = ObjectGenerator.create_borrower()
        loan = ObjectGenerator.create_loan(borrower["account_id"], 600_000, 6)
        net = loan["net_amount"]
        # Todas vencidas há 3 dias: o líquido do desembolso não cobre as seis.
        ObjectGenerator.make_installments_due(loan["loan_id"], range(1, 7), days_ago=3)

        ObjectGenerator.run_job("collect_installments")

        assert ObjectGenerator.balance_of(borrower["account_id"]) == 0
        installments = ObjectGenerator.loan_of(loan["loan_id"])["installments"]
        assert sum(item["paid_amount"] for item in installments) == net
        assert installments[0]["status"] == "PAID", "da mais antiga para a mais nova"
        unpaid = [item for item in installments if item["remaining_amount"] > 0]
        assert unpaid and all(item["status"] == "OVERDUE" and item["days_overdue"] == 3 for item in unpaid)


class TestInvoiceJobs:
    def setup_wallet(self, initial_balance: int = 0, autopay: bool = None):
        customer = ObjectGenerator.create_active_account(initial_balance=initial_balance)
        wallet = ObjectGenerator.create_credit_wallet(customer["account_id"], total_limit=100_000, autopay=autopay)
        card = ObjectGenerator.create_card(customer["account_id"])
        return customer, wallet, card

    def test_close_invoices_closes_on_closing_day_and_opens_the_next(self):
        customer, wallet, card = self.setup_wallet()
        ObjectGenerator.create_credit_purchase(card["card_id"], 9_000, installment_count=3)
        invoice = ObjectGenerator.open_invoice_of(wallet["wallet_id"])

        ObjectGenerator.run_job("close_invoices")
        assert ObjectGenerator.invoice_of(invoice["invoice_id"])["status"] == "OPEN", "antes do dia, nada muda"

        ObjectGenerator.move_invoice_dates(invoice["invoice_id"], closing_days_ago=0, due_in_days=10)
        ObjectGenerator.run_job("close_invoices")
        ObjectGenerator.run_job("close_invoices")

        assert ObjectGenerator.invoice_of(invoice["invoice_id"])["status"] == "CLOSED"
        next_open = ObjectGenerator.open_invoice_of(wallet["wallet_id"])
        assert next_open["invoice_id"] != invoice["invoice_id"]
        assert next_open["reference_month"] > invoice["reference_month"]

    def test_invoice_closing_with_nothing_to_pay_is_born_paid(self):
        customer, wallet, card = self.setup_wallet(initial_balance=10_000)
        ObjectGenerator.create_credit_purchase(card["card_id"], 4_000)
        invoice = ObjectGenerator.open_invoice_of(wallet["wallet_id"])
        RequestGenerator.POST_invoice_payment(invoice["invoice_id"], {"amount": 4_000}, key())

        ObjectGenerator.move_invoice_dates(invoice["invoice_id"], closing_days_ago=1, due_in_days=7)
        ObjectGenerator.run_job("close_invoices")

        assert ObjectGenerator.invoice_of(invoice["invoice_id"])["status"] == "PAID"

    def test_mark_overdue_records_the_original_debt(self):
        customer, wallet, card = self.setup_wallet()
        ObjectGenerator.create_credit_purchase(card["card_id"], 7_000)
        invoice = ObjectGenerator.open_invoice_of(wallet["wallet_id"])
        ObjectGenerator.move_invoice_dates(invoice["invoice_id"], closing_days_ago=3, due_in_days=0)
        ObjectGenerator.run_job("close_invoices")

        ObjectGenerator.run_job("mark_overdue_invoices")
        assert ObjectGenerator.invoice_of(invoice["invoice_id"])["status"] == "CLOSED", "vence hoje: ainda não atrasou"

        ObjectGenerator.move_invoice_dates(invoice["invoice_id"], closing_days_ago=3, due_in_days=-1)
        ObjectGenerator.run_job("mark_overdue_invoices")
        ObjectGenerator.run_job("mark_overdue_invoices")

        overdue = ObjectGenerator.invoice_of(invoice["invoice_id"])
        assert overdue["status"] == "OVERDUE"
        assert overdue["original_debt_amount"] == 7_000

    def test_autopay_debits_once_what_the_balance_covers(self):
        customer, wallet, card = self.setup_wallet(initial_balance=3_000, autopay=True)
        ObjectGenerator.create_credit_purchase(card["card_id"], 5_000)
        invoice = ObjectGenerator.open_invoice_of(wallet["wallet_id"])
        ObjectGenerator.move_invoice_dates(invoice["invoice_id"], closing_days_ago=3, due_in_days=0)
        ObjectGenerator.run_job("close_invoices")

        ObjectGenerator.run_job("run_invoice_autopay")
        ObjectGenerator.run_job("run_invoice_autopay")

        after = ObjectGenerator.invoice_of(invoice["invoice_id"])
        assert after["paid_amount"] == 3_000, "um débito automático por fatura"
        assert after["status"] == "PARTIALLY_PAID"
        assert ObjectGenerator.balance_of(customer["account_id"]) == 0

    def test_autopay_ignores_wallets_without_it(self):
        customer, wallet, card = self.setup_wallet(initial_balance=10_000)
        ObjectGenerator.create_credit_purchase(card["card_id"], 5_000)
        invoice = ObjectGenerator.open_invoice_of(wallet["wallet_id"])
        ObjectGenerator.move_invoice_dates(invoice["invoice_id"], closing_days_ago=3, due_in_days=0)
        ObjectGenerator.run_job("close_invoices")

        ObjectGenerator.run_job("run_invoice_autopay")

        assert ObjectGenerator.invoice_of(invoice["invoice_id"])["paid_amount"] == 0
        assert ObjectGenerator.balance_of(customer["account_id"]) == 10_000


class TestCardAndTransferJobs:
    def test_expire_authorizations_releases_the_reserved_limit(self):
        customer = ObjectGenerator.create_active_account()
        wallet = ObjectGenerator.create_credit_wallet(customer["account_id"], total_limit=50_000)
        card = ObjectGenerator.create_card(customer["account_id"])
        payload = PayloadGenerator.create_authorization_payload(card["card_id"], 8_000)
        RequestGenerator.POST_card_authorization(payload)

        ObjectGenerator.expire_authorization_now(payload["authorization_id"])
        ObjectGenerator.run_job("expire_authorizations")
        ObjectGenerator.run_job("expire_authorizations")

        _, authorization = RequestGenerator.GET_card_authorization(payload["authorization_id"])
        assert authorization["status"] == "EXPIRED"
        _, after = RequestGenerator.GET_credit_wallet(wallet["wallet_id"])
        assert after["used_limit"] == 0

    @pytest.mark.skipif(local_today().weekday() >= 5, reason="o job só executa TED em dia útil, na janela do STR")
    def test_run_scheduled_teds_executes_the_ted_of_the_day(self):
        source = ObjectGenerator.create_active_account(initial_balance=50_000)
        day = local_today() + timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        status, transfer = RequestGenerator.POST_ted_transfer(
            source["account_id"], PayloadGenerator.create_ted_payload(20_000, day.isoformat()), key()
        )
        assert status == 202 and transfer["status"] == "SCHEDULED", transfer

        ObjectGenerator.schedule_ted_for_today(transfer["transfer_id"])
        result = ObjectGenerator.run_job("run_scheduled_teds")
        if result.get("skipped_reason"):
            pytest.skip(result["skipped_reason"])
        ObjectGenerator.run_job("run_scheduled_teds")

        _, after = RequestGenerator.GET_transfer(transfer["transfer_id"])
        assert after["status"] == "SENT"
        assert ObjectGenerator.balance_of(source["account_id"]) == 50_000 - 20_000 - after["fee"]

    def test_reconcile_without_rail_answer_never_assumes_an_outcome(self):
        payer = ObjectGenerator.create_active_account(initial_balance=20_000)
        status, transfer = RequestGenerator.POST_pix_transfer(
            payer["account_id"], PayloadGenerator.create_pix_manual_payload(5_000), key()
        )
        assert status == 202 and transfer["status"] == "SENT", transfer
        ObjectGenerator.leave_transfer_without_answer(transfer["transfer_id"], minutes=60)

        ObjectGenerator.run_job("reconcile_spi_str")

        _, after = RequestGenerator.GET_transfer(transfer["transfer_id"])
        assert after["status"] == "SENT"
        assert ObjectGenerator.balance_of(payer["account_id"]) == 15_000


class TestDispatchOutbox:
    def test_pending_events_are_delivered_once(self):
        """Pela porta da frente: o próprio job conta o que entregou.

        O despacho vai em lotes de 100, do mais antigo ao mais novo; primeiro
        esvazia o que a suíte já deixou pendente.
        """
        for _ in range(1_000):
            if ObjectGenerator.run_job("dispatch_outbox_events")["processed"] < 100:
                break
        assert ObjectGenerator.run_job("dispatch_outbox_events")["processed"] == 0

        borrower = ObjectGenerator.create_borrower()
        ObjectGenerator.create_loan(borrower["account_id"])

        # Linha de crédito alterada + contrato fechado: pelo menos dois eventos.
        first = ObjectGenerator.run_job("dispatch_outbox_events")
        assert first["processed"] >= 2
        assert first["outcomes"] == {"SENT": first["processed"]}

        again = ObjectGenerator.run_job("dispatch_outbox_events")
        assert again["processed"] == 0, "evento entregue não sai de novo"
