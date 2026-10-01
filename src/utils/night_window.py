from datetime import datetime, timedelta
from typing import Optional

# Janela noturna do limite de transferência (Res. BCB 142/2021 · horário
# de Brasília). Das 20h às 6h a soma das saídas tem teto próprio.
NIGHT_START_HOUR = 20
NIGHT_END_HOUR = 6


def night_window_start(local_now: datetime) -> Optional[datetime]:
    """Quando começou a janela noturna em que `local_now` está — ou None de dia.

    `local_now` é a hora de Brasília SEM fuso (naive): quem chama pega esse
    valor do próprio Postgres (`now() AT TIME ZONE 'America/Sao_Paulo'`),
    que tem a base de fusos dele. Assim a regra não depende de a imagem
    Docker do Python ter o pacote de fusos instalado.

    Às 23h de terça, a janela começou às 20h de terça. Às 2h de quarta,
    ela começou às 20h de TERÇA — a madrugada pertence à noite anterior.
    """
    if local_now.hour >= NIGHT_START_HOUR:
        return local_now.replace(hour=NIGHT_START_HOUR, minute=0, second=0, microsecond=0)

    if local_now.hour < NIGHT_END_HOUR:
        yesterday = local_now - timedelta(days=1)
        return yesterday.replace(hour=NIGHT_START_HOUR, minute=0, second=0, microsecond=0)

    return None
