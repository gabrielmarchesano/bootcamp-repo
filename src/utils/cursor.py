import base64
import json
from datetime import datetime
from typing import Optional, Tuple


def encode_cursor(created_at: datetime, row_id) -> str:
    """Empacota a posição (created_at, id) da última linha devolvida.

    O cursor é OPACO de propósito: quem chama não deve montar nem editar o
    valor, só devolvê-lo. Isso deixa a gente trocar o que vai dentro (outra
    coluna de ordenação, por exemplo) sem quebrar ninguém.
    """
    raw = json.dumps({"t": created_at.isoformat(), "i": str(row_id)})
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: Optional[str]) -> Optional[Tuple[datetime, str]]:
    """Desempacota o cursor. Qualquer coisa que não seja um cursor nosso levanta ValueError."""
    if cursor is None:
        return None

    padded = cursor + "=" * (-len(cursor) % 4)
    raw = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))

    if not isinstance(raw, dict) or "t" not in raw or "i" not in raw:
        raise ValueError("malformed cursor")

    created_at = datetime.fromisoformat(raw["t"])
    if created_at.tzinfo is None:
        raise ValueError("cursor without timezone")

    return created_at, str(raw["i"])
