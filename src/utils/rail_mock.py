"""Consulta de status no SPI e no STR — mock.

No trilho de verdade, a reconciliação pergunta ao SPI (pacs.002/consulta
de status) e ao STR o desfecho de uma mensagem que ficou sem retorno. Aqui
não há trilho: a consulta devolve None ("sem resposta"), e o job deixa a
transferência como está. Nunca se assume sucesso nem falha por timeout.

Respostas possíveis (quando houver trilho): {"status": "SETTLED"},
{"status": "REJECTED", "error_code": "..."} no SPI, {"status": "RETURNED",
"reason": "..."} no STR.
"""

from typing import Optional


def query_transfer_status(rail: str, external_id: str) -> Optional[dict]:
    return None
