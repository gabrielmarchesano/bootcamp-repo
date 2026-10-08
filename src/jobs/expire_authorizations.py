"""APPROVED → EXPIRED depois de expires_at: libera HOLD e reserva não capturados."""
from jobs.runner import main

if __name__ == "__main__":
    main("expire_authorizations")
