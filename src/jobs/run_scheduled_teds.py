"""Executa as TEDs SCHEDULED do dia (dentro da janela do STR): SENT ou FAILED."""
from jobs.runner import main

if __name__ == "__main__":
    main("run_scheduled_teds")
