from typing import Optional
from uuid import UUID


def parse_uuid(raw_value: str) -> Optional[UUID]:
    """Converte o id do endereço em UUID, ou devolve None se não for um.

    Sem isto, `GET /accounts/abc` chegaria ao Postgres como
    `WHERE id = 'abc'` e voltaria um erro de sintaxe — 500, a API culpando
    a si mesma. Id que não é UUID não aponta para nada: quem chama trata
    None como "não encontrado" (404).
    """
    try:
        return UUID(str(raw_value))
    except (ValueError, TypeError, AttributeError):
        return None
