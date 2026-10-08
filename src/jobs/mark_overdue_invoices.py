"""Fatura vencida e não quitada → OVERDUE, gravando original_debt_amount."""
from jobs.runner import main

if __name__ == "__main__":
    main("mark_overdue_invoices")
