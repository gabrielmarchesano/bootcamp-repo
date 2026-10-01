import functools
import time

from sqlalchemy.exc import DBAPIError

from utils.logger import get_logger


logger = get_logger(__name__)

# 40P01 = deadlock_detected · 40001 = serialization_failure.
# São os dois erros em que o Postgres DESFAZ a transação e diz, com todas
# as letras, "pode tentar de novo". Nenhum outro erro entra nesta lista.
RETRYABLE_PGCODES = ("40P01", "40001")


def retry_on_deadlock(max_attempts: int = 3, base_delay_seconds: float = 0.05):
    """Repete o método do controller quando o banco aborta por deadlock.

    Com a ordem global de lock (contas sempre por id crescente) o deadlock
    não deveria acontecer. Este decorator é o cinto de segurança para o dia
    em que alguém escrever um caminho novo que trave fora de ordem: em vez
    de 500, o cliente recebe a resposta certa, com um atraso de milissegundos.

    Por que no controller e não no repository: o que se repete é a
    TRANSAÇÃO inteira (ler, travar, decidir, gravar). Repetir só o último
    comando, numa transação que o Postgres já abortou, não funciona.

    Exige que o método decorado seja de um controller (tem `self.session`).
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(self, *args, **kwargs)
                except DBAPIError as error:
                    pgcode = getattr(error.orig, "pgcode", None)
                    if pgcode not in RETRYABLE_PGCODES or attempt == max_attempts:
                        raise

                    self.session.rollback()
                    delay = base_delay_seconds * (2 ** (attempt - 1))
                    logger.warning(f"{func.__name__}: pgcode {pgcode}, tentativa {attempt} de {max_attempts}")
                    time.sleep(delay)

        return wrapper

    return decorator
