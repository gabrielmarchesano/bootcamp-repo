"""Jobs agendados. Cada um roda com `python -m jobs.<nome>` (a partir de src/)
ou pela rota interna `POST /job/<nome>`. A lógica mora no JobController."""

JOB_NAMES = (
    "collect_installments",
    "run_scheduled_teds",
    "reconcile_spi_str",
    "expire_authorizations",
    "close_invoices",
    "run_invoice_autopay",
    "mark_overdue_invoices",
    "dispatch_outbox_events",
)
