from errors import QIException

# ════════════════════════════════════════════════════════════════════
# Códigos APOSENTADOS — não reutilizar
# ════════════════════════════════════════════════════════════════════
# QIT001001, 001002, 001004, 001005 e 001006 eram do sample_entity, que
# saiu do projeto. Um código de erro é contrato: quem integrou programou
# em cima dele. Reaproveitar o número para outro significado faria um
# cliente antigo tratar o erro novo como se fosse o velho. Número que
# morre fica morto.
#
# QIT001003 (CPF inválido) e QIT001007 (data inexistente) continuam: o
# cadastro de cliente usa os dois.


class InvalidDocumentNumber(QIException):
    """O CPF tem o formato certo e não existe.

    422, e não 400, de propósito: 400 quer dizer "não consegui ler o seu
    pedido". Aqui a API leu, entendeu, e o valor é que não pode existir —
    os dois últimos dígitos não batem com a conta. A diferença está
    explicada em src/utils/document_number.py.
    """

    code = "QIT001003"

    def __init__(self, document_number) -> None:
        title = "Invalid Document Number"
        http_status = 422
        description = f"The document number {document_number} is not a valid CPF."
        translation = "O CPF informado não é válido."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidBirthdate(QIException):
    """A data tem o formato certo e não existe no calendário.

    Existe porque o `pattern` do schema sabe contar dígitos, não dias:
    "2025-02-30" e "9999-99-99" passam pelo regex e morrem no
    `date.fromisoformat`. Sem esta classe, esse ValueError virava 500 —
    a API culpando a si mesma por um erro de quem chamou.
    """

    code = "QIT001007"

    def __init__(self, birthdate) -> None:
        title = "Invalid Birthdate"
        http_status = 422
        description = f"The birthdate {birthdate} is not a real date."
        translation = "A data de nascimento informada não existe."
        super().__init__(title, self.code, http_status, description, translation)


# ════════════════════════════════════════════════════════════════════
# Conta digital + microcrédito
# ════════════════════════════════════════════════════════════════════
# Faixa QIT001008 em diante. A tabela "código de contrato → QIT" está em
# docs/api-contract.md, seção "Códigos de erro".


class CustomerNotFound(QIException):
    code = "QIT001008"

    def __init__(self, customer_id) -> None:
        title = "Customer not Found"
        http_status = 404
        description = f"Customer {customer_id} was not found."
        translation = "Cliente não encontrado."
        super().__init__(title, self.code, http_status, description, translation)


class AccountNotFound(QIException):
    """404 também para conta interna (LOAN_PORTFOLIO, FEE_REVENUE...).

    Conta interna existe, mas não é assunto de quem chama a API. Responder
    404 em vez de 403 não confirma que aquele id existe.
    """

    code = "QIT001009"

    def __init__(self, account_id) -> None:
        title = "Account not Found"
        http_status = 404
        description = f"Account {account_id} was not found."
        translation = "Conta não encontrada."
        super().__init__(title, self.code, http_status, description, translation)


class CustomerAlreadyExists(QIException):
    code = "QIT001010"

    def __init__(self, field_name, value) -> None:
        title = "Customer already registered"
        http_status = 409
        description = f"There is already a customer with {field_name} {value}."
        translation = f"Já existe um cliente com este {field_name.upper()}."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidCnpj(QIException):
    code = "QIT001011"

    def __init__(self, cnpj) -> None:
        title = "Invalid CNPJ"
        http_status = 422
        description = f"The document number {cnpj} is not a valid CNPJ."
        translation = "O CNPJ informado não é válido."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidStatusTransition(QIException):
    code = "QIT001012"

    def __init__(self, old_status, new_status) -> None:
        title = "Invalid status transition"
        http_status = 409
        description = f"Account with status {old_status} cannot change to {new_status}."
        translation = "Essa mudança de status não é permitida."
        super().__init__(title, self.code, http_status, description, translation)


class AccountNotActive(QIException):
    code = "QIT001013"

    def __init__(self, account_id, status) -> None:
        title = "Account not active"
        http_status = 409
        description = f"Account {account_id} has status {status} and cannot move money."
        translation = "A conta não está ativa."
        super().__init__(title, self.code, http_status, description, translation)


class AccountCannotBeClosed(QIException):
    code = "QIT001014"

    def __init__(self, reason) -> None:
        title = "Account cannot be closed"
        http_status = 409
        description = f"Account cannot be closed: {reason}."
        translation = "A conta só pode ser encerrada com saldo zero e sem contrato ativo."
        super().__init__(title, self.code, http_status, description, translation)


class IdempotencyKeyRequired(QIException):
    """Toda rota que move dinheiro exige o header Idempotency-Key.

    400 e não 422: sem a chave, a API não consegue nem LER o pedido com
    segurança — não teria como saber se ele é novo ou uma repetição.
    """

    code = "QIT001015"

    def __init__(self) -> None:
        title = "Idempotency-Key required"
        http_status = 400
        description = "Header Idempotency-Key is required (8 to 64 chars: letters, digits, '-' or '_')."
        translation = "O header Idempotency-Key é obrigatório."
        super().__init__(title, self.code, http_status, description, translation)


class IdempotencyConflict(QIException):
    code = "QIT001016"

    def __init__(self, idempotency_key) -> None:
        title = "Idempotency conflict"
        http_status = 409
        description = f"Idempotency-Key {idempotency_key} was already used with a different payload."
        translation = "Esta chave de idempotência já foi usada com outro conteúdo."
        super().__init__(title, self.code, http_status, description, translation)


class InsufficientBalance(QIException):
    code = "QIT001017"

    def __init__(self, required, available) -> None:
        title = "Insufficient balance"
        http_status = 422
        description = f"Operation requires {required} cents and only {available} are available."
        translation = "Saldo insuficiente."
        super().__init__(title, self.code, http_status, description, translation)


class SameAccountTransfer(QIException):
    code = "QIT001018"

    def __init__(self) -> None:
        title = "Same account"
        http_status = 422
        description = "Source and destination accounts must be different."
        translation = "A conta de origem e a de destino precisam ser diferentes."
        super().__init__(title, self.code, http_status, description, translation)


class NightLimitExceeded(QIException):
    code = "QIT001019"

    def __init__(self, limit, already_used) -> None:
        title = "Night limit exceeded"
        http_status = 422
        description = f"Night limit is {limit} cents (20h-6h) and {already_used} were already used."
        translation = "Limite noturno de transferência excedido."
        super().__init__(title, self.code, http_status, description, translation)


class TransferNotFound(QIException):
    code = "QIT001020"

    def __init__(self, transfer_id) -> None:
        title = "Transfer not Found"
        http_status = 404
        description = f"Transfer {transfer_id} was not found."
        translation = "Transferência não encontrada."
        super().__init__(title, self.code, http_status, description, translation)
