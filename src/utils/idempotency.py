import hashlib
import json
import re

# Formato aceito para o header Idempotency-Key: o mesmo alfabeto seguro do
# X-Request-ID (letras, números, hífen, sublinhado), de 8 a 64 caracteres.
# Um UUID cabe; uma frase com espaço, não.
UUID_V4 = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}")

def is_valid_idempotency_key(idempotency_key: str) -> bool:
    return idempotency_key is not None and UUID_V4.fullmatch(idempotency_key) is not None
 

def request_hash(payload: dict) -> str:
    """O SHA-256 do corpo, em forma canônica.

    `sort_keys` e os separadores fixos fazem o mesmo JSON, escrito com as
    chaves em outra ordem ou com outro espaçamento, gerar o MESMO hash. Sem
    isso, um cliente que reenvia o mesmo pedido montado por outra biblioteca
    levaria um 409 de conflito por causa de um espaço.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
