"""Regras de formato do Pix que não dependem de banco.

Tudo aqui é função pura: entra texto, sai texto. Quem decide o que fazer
com o resultado é o controller.
"""

import re
import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from constants import OWN_ISPB

_ALPHANUMERIC = string.ascii_letters + string.digits

# Formato BCB: prefixo + ISPB (8) + yyyyMMddHHmm (UTC) + 11 alfanuméricos = 32.
# "E" identifica um pagamento; "D", uma devolução.
PAYMENT_PREFIX = "E"
REVERSAL_PREFIX = "D"

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PHONE = re.compile(r"\+55\d{10,11}")
_EVP = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def generate_end_to_end_id(prefix: str = PAYMENT_PREFIX, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    suffix = "".join(secrets.choice(_ALPHANUMERIC) for _ in range(11))
    return f"{prefix}{OWN_ISPB}{now.strftime('%Y%m%d%H%M')}{suffix}"


def detect_key_type(pix_key: str) -> Optional[str]:
    """O tipo da chave pelo formato, como o DICT faz. None = não é chave Pix.

    A ordem importa: 11 dígitos é CPF, 14 é CNPJ, e só depois vem o resto.
    """
    if re.fullmatch(r"\d{11}", pix_key):
        return "CPF"
    if re.fullmatch(r"\d{14}", pix_key):
        return "CNPJ"
    if _PHONE.fullmatch(pix_key):
        return "PHONE"
    if _EVP.fullmatch(pix_key):
        return "EVP"
    if _EMAIL.fullmatch(pix_key) and len(pix_key) <= 77:
        return "EMAIL"
    return None


def mask_document(document: str) -> str:
    """Documento mascarado como o DICT devolve (QI: owner_masked_document)."""
    if len(document) == 11:
        return f"***.{document[3:6]}.{document[6:9]}-**"
    return f"**.***.{document[5:8]}/{document[8:12]}-**"


def has_emoji(text: Optional[str]) -> bool:
    """A QI recusa emoji na mensagem do Pix (PXT000048).

    Pega o que está fora do plano básico do Unicode (a maioria dos emojis)
    e os blocos de símbolos e dingbats que também viram figurinha.
    """
    if not text:
        return False
    for character in text:
        code = ord(character)
        if code > 0xFFFF or 0x2600 <= code <= 0x27BF or code == 0xFE0F:
            return True
    return False