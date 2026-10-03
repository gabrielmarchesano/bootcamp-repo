from database import Context


class EnumeratorRepository:
    """Traduz o nome de um estado ("ACTIVE") na linha da tabela de enumerador.

    O código sempre fala o NOME; o id é detalhe do banco. Estado que não
    existe na tabela estoura aqui (NoResultFound → 500), e isso é o certo:
    não é erro de quem chamou a API, é bug de quem escreveu o código.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get(self, enumerator_model, enumerator: str):
        """Busca SEM autoflush, de propósito.

        Toda consulta do SQLAlchemy grava antes o que está pendente na
        sessão. No cadastro, isso mandava o INSERT do cliente para o banco
        AQUI, fora do `try` do controller que traduz CPF duplicado em 409:
        a corrida de dois cadastros iguais virava 500. Tabela de enumerador
        é estática e não depende de nada pendente, então não há o que gravar
        antes de lê-la.
        """
        with self.session.no_autoflush:
            return (
                self.session.query(enumerator_model)
                .filter(enumerator_model.enumerator == enumerator)
                .one()
            )