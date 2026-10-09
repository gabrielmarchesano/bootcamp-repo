from sqlalchemy.types import UserDefinedType


class PgEnum(UserDefinedType):
    """Coluna de um tipo enum do Postgres (CREATE TYPE enum_* no database.sql).

    No Python o valor continua sendo uma string comum — as constantes dos
    models (ex.: LedgerEntry.PIX_SENT) seguem valendo. A diferença está no SQL:
    mapear como String faz o SQLAlchemy, no INSERT de várias linhas, gerar
    `%(param)s::VARCHAR`, que o Postgres recusa numa coluna enum
    ("column ... is of type enum_... but expression is of type character
    varying"). Com este tipo, o cast sai com o nome do enum.

    Os valores válidos ficam só no database.sql: o banco é quem recusa um
    valor fora da lista.
    """

    cache_ok = True

    def __init__(self, name: str):
        self.name = name

    def get_col_spec(self, **kw):
        return self.name
