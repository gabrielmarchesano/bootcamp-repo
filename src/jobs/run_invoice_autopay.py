"""Débito automático da fatura no vencimento, no máximo um por fatura."""
from jobs.runner import main

if __name__ == "__main__":
    main("run_invoice_autopay")
