"""OPEN → CLOSED no dia de corte; a FUTURE seguinte vira OPEN."""
from jobs.runner import main

if __name__ == "__main__":
    main("close_invoices")
