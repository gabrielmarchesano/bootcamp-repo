"""KYC/PLD de mentirinha — o lugar onde o serviço de verdade vai encaixar.

O fluxo v6 prevê uma checagem de KYC/PLD ANTES da regra de idade. Num banco
de verdade, essa checagem é um serviço de fora (bureau, lista restritiva,
COAF) e entraria por um connector em src/connectors/, como o de boletos.

Até lá, a regra é determinística para os testes conseguirem provocar os
dois desfechos: todo CPF é aprovado, menos os desta lista. São CPFs
válidos (passam no dígito verificador) escolhidos para representar
"pessoa em lista restritiva".
"""

KYC_REJECTED_CPFS = {
    "52998224725",
}

APPROVED = "APPROVED"
REJECTED = "REJECTED"


def check_kyc(cpf: str) -> str:
    if cpf in KYC_REJECTED_CPFS:
        return REJECTED

    return APPROVED
