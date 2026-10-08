"""Entrega à IF os eventos PENDING do outbox (baas.<recurso>.<evento>)."""
from jobs.runner import main

if __name__ == "__main__":
    main("dispatch_outbox_events")
