"""Roda um job fora de uma requisição HTTP.

Na API, quem abre e fecha o contexto (e a sessão de banco) é o middleware
session_manager. Aqui não há requisição: este runner faz o papel dele —
abre o contexto, roda o job, e fecha a sessão sempre, deu certo ou não.

    cd src && python -m jobs.collect_installments
"""

import json
import sys

from constants import check_variables
from database import clear_context, open_context
from utils.logger import setup_logging


def run(job_name: str) -> dict:
    check_variables()
    setup_logging()

    # Import tardio: os controllers pedem o contexto ao serem construídos.
    from controllers import JobController

    context = open_context()
    try:
        return JobController().run(job_name)
    except Exception:
        if context.db_session is not None:
            context.db_session.rollback()
        raise
    finally:
        if context.db_session is not None:
            context.db_session.close()
        clear_context()


def main(job_name: str) -> None:
    result = run(job_name)
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
