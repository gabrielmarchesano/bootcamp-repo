import hashlib
import json
import re

# Formato aceito para o header Idempotency-Key: o mesmo alfabeto seguro do
# X-Request-ID (letras, números, hífen, sublinhado), de 8 a 64 caracteres.
# Um UUID cabe; uma frase com espaço, não.
SAFE_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_-]{8,64}")


def is_valid_idempotency_key(idempotency_key: str) -> bool:
    return idempotency_key is not None and SAFE_IDEMPOTENCY_KEY.fullmatch(idempotency_key) is not None


def request_hash(payload: dict) -> str:
    """O SHA-256 do corpo, em forma canônica.

    `sort_keys` e os separadores fixos fazem o mesmo JSON, escrito com as
    chaves em outra ordem ou com outro espaçamento, gerar o MESMO hash. Sem
    isso, um cliente que reenvia o mesmo pedido montado por outra biblioteca
    levaria um 409 de conflito por causa de um espaço.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
