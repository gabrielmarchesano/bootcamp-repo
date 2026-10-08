"""Diário: debita parcelas vencidas; sem saldo, marca OVERDUE e avisa a IF."""
from jobs.runner import main

if __name__ == "__main__":
    main("collect_installments")
