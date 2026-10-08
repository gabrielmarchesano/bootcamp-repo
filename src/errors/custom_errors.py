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
        description = "Header Idempotency-Key is required and must be a UUID v4."
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


# ════════════════════════════════════════════════════════════════════
# Sprint 2b (Pix/TED) e sprint 4 (cartões) — padrão QI Tech
# ════════════════════════════════════════════════════════════════════
# Cada classe cita o código equivalente da QI quando existe. A tabela
# completa está em docs/api-contract.md.


class PixKeyNotFound(QIException):
    """QI PIX000017."""

    code = "QIT001021"

    def __init__(self, pix_key) -> None:
        title = "Pix Key Not Found"
        http_status = 404
        description = f"Pix key {pix_key} not found."
        translation = "A chave Pix não foi encontrada."
        super().__init__(title, self.code, http_status, description, translation)


class EndToEndIdAlreadyUsed(QIException):
    """QI PXT000061: o e2e da consulta vale para UMA transferência, tenha dado certo ou não."""

    code = "QIT001022"

    def __init__(self, end_to_end_id) -> None:
        title = "End to end id already used"
        http_status = 409
        description = f"End to end id {end_to_end_id} was already used by another transfer."
        translation = "Este end_to_end_id já foi usado em outra transferência."
        super().__init__(title, self.code, http_status, description, translation)


class PixKeyInquiryExpired(QIException):
    code = "QIT001023"

    def __init__(self, end_to_end_id) -> None:
        title = "Pix key inquiry expired"
        http_status = 422
        description = f"The Pix key inquiry for {end_to_end_id} has expired. Query the key again."
        translation = "A consulta da chave expirou. Consulte a chave de novo."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidPixMessage(QIException):
    """QI PXT000048."""

    code = "QIT001024"

    def __init__(self) -> None:
        title = "Invalid Pix message"
        http_status = 422
        description = "Emoji not allowed in pix message."
        translation = "Emoji não é permitido na mensagem Pix."
        super().__init__(title, self.code, http_status, description, translation)


class TedOutsideWindow(QIException):
    """QI TED000011: fora da janela a TED é recusada, não reagendada por conta própria."""

    code = "QIT001025"

    def __init__(self) -> None:
        title = "Wrong day/time for TED"
        http_status = 422
        description = "TED is only sent on business days from 06:30 to 17:00. Send schedule_date to schedule it."
        translation = "TED só sai em dia útil, das 6h30 às 17h. Envie schedule_date para agendar."
        super().__init__(title, self.code, http_status, description, translation)


class ReversalExceedsReceived(QIException):
    """QI PXT000017."""

    code = "QIT001026"

    def __init__(self, total, received) -> None:
        title = "Reversal too great"
        http_status = 422
        description = f"Reversals would sum {total} cents, above the {received} cents received."
        translation = "A soma das devoluções ultrapassa o valor recebido."
        super().__init__(title, self.code, http_status, description, translation)


class ReversalWindowExpired(QIException):
    """QI PXT000015."""

    code = "QIT001027"

    def __init__(self) -> None:
        title = "Reversal date expired"
        http_status = 422
        description = "The original Pix is older than 90 days."
        translation = "O Pix original é mais antigo que 90 dias."
        super().__init__(title, self.code, http_status, description, translation)


class TransferCannotBeCanceled(QIException):
    """QI PSC000028."""

    code = "QIT001028"

    def __init__(self, status) -> None:
        title = "Transfer cannot be canceled"
        http_status = 409
        description = f"Transfer with status {status} cannot be canceled. Only SCHEDULED can."
        translation = "Só transferência agendada pode ser cancelada."
        super().__init__(title, self.code, http_status, description, translation)


class PixKeyAlreadyRegistered(QIException):
    code = "QIT001029"

    def __init__(self, pix_key) -> None:
        title = "Pix key already registered"
        http_status = 409
        description = f"Pix key {pix_key} is already registered."
        translation = "Esta chave Pix já está registrada."
        super().__init__(title, self.code, http_status, description, translation)


class CreditWalletAlreadyExists(QIException):
    """QI CIN000043."""

    code = "QIT001030"

    def __init__(self, account_id) -> None:
        title = "Active wallet found"
        http_status = 409
        description = f"Account {account_id} already has a live credit wallet."
        translation = "Já existe uma carteira de crédito ativa para esta conta."
        super().__init__(title, self.code, http_status, description, translation)


class LimitBelowUsed(QIException):
    """QI CIN000110."""

    code = "QIT001031"

    def __init__(self, new_limit, used_limit) -> None:
        title = "Limit below used"
        http_status = 422
        description = f"New limit {new_limit} is less than used limit {used_limit}."
        translation = "O novo limite é menor que o valor já utilizado."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidResourceStatusTransition(QIException):
    """QI CARD000013. Vale para cartão e carteira; a da conta segue no QIT001012."""

    code = "QIT001032"

    def __init__(self, resource, old_status, new_status) -> None:
        title = "Invalid status transition"
        http_status = 409
        description = f"{resource} with status {old_status} cannot change to {new_status}."
        translation = "Essa mudança de status não é permitida."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidActivationCode(QIException):
    """QI CARD000020. O código nunca aparece na mensagem."""

    code = "QIT001033"

    def __init__(self) -> None:
        title = "Invalid activation code"
        http_status = 422
        description = "Invalid activation code."
        translation = "Código de ativação inválido."
        super().__init__(title, self.code, http_status, description, translation)


class PlasticCardOnly(QIException):
    """QI CARD000023."""

    code = "QIT001034"

    def __init__(self) -> None:
        title = "Invalid card type"
        http_status = 422
        description = "This operation is only valid for PLASTIC cards."
        translation = "Operação válida só para cartão físico."
        super().__init__(title, self.code, http_status, description, translation)


class RefundExceedsCapture(QIException):
    code = "QIT001035"

    def __init__(self, total, captured) -> None:
        title = "Refund exceeds capture"
        http_status = 422
        description = f"Refunds would sum {total} cents, above the {captured} cents captured."
        translation = "O estorno ultrapassa o valor capturado."
        super().__init__(title, self.code, http_status, description, translation)


class PixKeyInquiryNotFound(QIException):
    """QI PIX000056."""

    code = "QIT001036"

    def __init__(self, end_to_end_id) -> None:
        title = "Pix key inquiry not found"
        http_status = 404
        description = f"No Pix key inquiry with end_to_end_id {end_to_end_id} for this account."
        translation = "Consulta de chave Pix não encontrada para esta conta."
        super().__init__(title, self.code, http_status, description, translation)


class PixKeyMismatch(QIException):
    """QI PXT000128."""

    code = "QIT001037"

    def __init__(self) -> None:
        title = "Pix key mismatch"
        http_status = 422
        description = "Pix key sent does not match the inquiry. Verify the end_to_end_id."
        translation = "A chave enviada não é a da consulta. Confira o end_to_end_id."
        super().__init__(title, self.code, http_status, description, translation)


class IncomingTransferNotFound(QIException):
    code = "QIT001038"

    def __init__(self, incoming_transfer_id) -> None:
        title = "Incoming transfer not found"
        http_status = 404
        description = f"Incoming transfer {incoming_transfer_id} was not found."
        translation = "Entrada não encontrada."
        super().__init__(title, self.code, http_status, description, translation)


class IncomingTransferNotReversible(QIException):
    code = "QIT001039"

    def __init__(self, reason) -> None:
        title = "Incoming transfer cannot be reversed"
        http_status = 422
        description = f"Incoming transfer cannot be reversed: {reason}."
        translation = "Esta entrada não pode ser devolvida."
        super().__init__(title, self.code, http_status, description, translation)


class PixKeyLimitReached(QIException):
    """Regulamento Pix: 5 chaves por conta de pessoa física, 20 de pessoa jurídica."""

    code = "QIT001040"

    def __init__(self, limit) -> None:
        title = "Pix key limit reached"
        http_status = 409
        description = f"Account already has {limit} active Pix keys."
        translation = "A conta já tem o número máximo de chaves Pix."
        super().__init__(title, self.code, http_status, description, translation)


class PixKeyNotOwned(QIException):
    code = "QIT001041"

    def __init__(self, key_type) -> None:
        title = "Pix key not owned"
        http_status = 422
        description = f"Pix key of type {key_type} must be the account holder's own document."
        translation = "Chave CPF/CNPJ precisa ser o documento do titular."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidTargetAccount(QIException):
    """QI PXT000132/PXT000141/TED000071."""

    code = "QIT001042"

    def __init__(self, reason) -> None:
        title = "Invalid target account"
        http_status = 422
        description = f"Invalid target account: {reason}."
        translation = "Conta de destino inválida."
        super().__init__(title, self.code, http_status, description, translation)


class CardNotFound(QIException):
    """QI CARD000011."""

    code = "QIT001043"

    def __init__(self, card_id) -> None:
        title = "Card not found"
        http_status = 404
        description = f"Card {card_id} was not found."
        translation = "Cartão não encontrado."
        super().__init__(title, self.code, http_status, description, translation)


class CreditWalletNotFound(QIException):
    """QI CIN000007."""

    code = "QIT001044"

    def __init__(self, wallet_id) -> None:
        title = "Wallet not found"
        http_status = 404
        description = f"Wallet {wallet_id} was not found."
        translation = "Carteira não encontrada."
        super().__init__(title, self.code, http_status, description, translation)


class CreditWalletRequired(QIException):
    code = "QIT001045"

    def __init__(self) -> None:
        title = "Credit wallet required"
        http_status = 422
        description = "A card with credit function needs an ACTIVE credit wallet on the account."
        translation = "Cartão com função crédito exige carteira de crédito ativa."
        super().__init__(title, self.code, http_status, description, translation)


class AuthorizationNotFound(QIException):
    code = "QIT001046"

    def __init__(self, authorization_id) -> None:
        title = "Authorization not found"
        http_status = 404
        description = f"Authorization {authorization_id} was not found."
        translation = "Autorização não encontrada."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidAuthorizationState(QIException):
    code = "QIT001047"

    def __init__(self, status, operation) -> None:
        title = "Invalid authorization state"
        http_status = 409
        description = f"Authorization with status {status} does not accept {operation}."
        translation = "A autorização não aceita esta operação no status atual."
        super().__init__(title, self.code, http_status, description, translation)


class InvoiceNotFound(QIException):
    code = "QIT001048"

    def __init__(self, invoice_id) -> None:
        title = "Invoice not found"
        http_status = 404
        description = f"Invoice {invoice_id} was not found."
        translation = "Fatura não encontrada."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidScheduleDate(QIException):
    """QI PSC000008."""

    code = "QIT001049"

    def __init__(self) -> None:
        title = "Invalid schedule date"
        http_status = 422
        description = "schedule_date must be a business day after today."
        translation = "A data de agendamento precisa ser um dia útil depois de hoje."
        super().__init__(title, self.code, http_status, description, translation)


# ════════════════════════════════════════════════════════════════════
# Etapa 1 — titular v7
# ════════════════════════════════════════════════════════════════════


class InvalidEiOwner(QIException):
    """O dono de um EI (empresário individual) tem de ser pessoa natural.

    O v7 modela o EI/MEI como um CNPJ (LEGAL) cujo patrimônio é o da
    pessoa física que o abriu (owner_customer_id -> NATURAL). Apontar o
    dono para uma PJ quebra essa premissa.
    """

    code = "QIT001050"

    def __init__(self, owner_customer_id) -> None:
        title = "Invalid EI owner"
        http_status = 422
        description = f"The owner {owner_customer_id} of an EI must be a NATURAL person."
        translation = "O dono do EI precisa ser uma pessoa física."
        super().__init__(title, self.code, http_status, description, translation)


class AdditionalAccountNotAllowed(QIException):
    """Regra de abertura de conta adicional violada (QIT001051).

    O titular precisa estar com o KYC aprovado para que uma conta
    adicional nasça ACTIVE reaproveitando o status do titular; sem isso,
    não há conta nova a abrir por esta rota.
    """

    code = "QIT001051"

    def __init__(self, reason) -> None:
        title = "Additional account not allowed"
        http_status = 422
        description = f"Cannot open an additional account: {reason}."
        translation = "Não é possível abrir uma conta adicional para este titular."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidRelationship(QIException):
    """Regra de vínculo (PARTNER/ADMINISTRATOR/ATTORNEY) violada (QIT001052).

    O lado legal precisa ser LEGAL e o natural NATURAL; o par
    (legal, natural, role) não pode repetir.
    """

    code = "QIT001052"

    def __init__(self, reason) -> None:
        title = "Invalid relationship"
        http_status = 422
        description = f"Invalid customer relationship: {reason}."
        translation = "Vínculo entre titulares inválido."
        super().__init__(title, self.code, http_status, description, translation)