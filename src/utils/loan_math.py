"""A conta do microcrédito — pura, sem banco.

Convenções do time (premissas da RFC):
  • Parcelas a cada 30 dias, sistema Price (parcela fixa, juros sobre o saldo).
  • Dinheiro em centavos inteiros; cada valor é arredondado para o centavo
    (ROUND_HALF_UP) e a última parcela absorve a sobra do arredondamento,
    para o principal fechar exato.
  • TAC proporcional abaixo de 120 dias (Res. CMN 4.854/2020):
    taxa efetiva = taxa da linha × prazo / 120.
  • CET mensal = TIR dos fluxos (recebe o líquido, paga as parcelas);
    CET anual = (1 + CET mensal)^12 − 1.
  • Desconto de antecipação (CDC art. 52 §2º): a parcela futura vale o seu
    valor presente à taxa do contrato, descontado pelos dias que faltam;
    o desconto nunca passa dos juros ainda em aberto da parcela (paga-se
    sempre, no mínimo, o principal).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, List

PERIOD_DAYS = 30
FULL_FEE_TERM_DAYS = 120

SIX_PLACES = Decimal("0.000001")


def to_cents(value: Decimal) -> int:
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_rate(value) -> Decimal:
    return Decimal(str(value)).quantize(SIX_PLACES, rounding=ROUND_HALF_UP)


@dataclass
class ScheduledInstallment:
    number: int
    due_date: date
    principal_amount: int
    interest_amount: int

    @property
    def total_amount(self) -> int:
        return self.principal_amount + self.interest_amount


@dataclass
class LoanTerms:
    principal_amount: int
    installment_count: int
    term_days: int
    monthly_interest_rate: Decimal
    effective_fee_rate: Decimal
    origination_fee_amount: int
    net_amount: int
    effective_cost_monthly: Decimal
    effective_cost_annual: Decimal
    installments: List[ScheduledInstallment]


def effective_fee_rate(origination_fee_rate, term_days: int) -> Decimal:
    rate = Decimal(str(origination_fee_rate))
    if term_days < FULL_FEE_TERM_DAYS:
        rate = rate * Decimal(term_days) / Decimal(FULL_FEE_TERM_DAYS)
    return to_rate(rate)


def price_schedule(
    principal: int,
    monthly_rate,
    installment_count: int,
    first_day: date,
    adjust_due_date: Callable[[date], date],
) -> List[ScheduledInstallment]:
    """Cronograma Price: parcela fixa; juros = saldo × taxa; principal = parcela − juros."""
    rate = Decimal(str(monthly_rate))
    payment = Decimal(principal) * rate / (1 - (1 + rate) ** -installment_count)

    balance = principal
    schedule = []
    for number in range(1, installment_count + 1):
        interest = to_cents(Decimal(balance) * rate)
        if number == installment_count:
            principal_part = balance
        else:
            principal_part = min(to_cents(payment) - interest, balance)
        balance -= principal_part

        due = adjust_due_date(first_day + timedelta(days=PERIOD_DAYS * number))
        schedule.append(ScheduledInstallment(number, due, principal_part, interest))

    return schedule


def monthly_irr(net_amount: int, payments: List[int]) -> Decimal:
    """Taxa mensal que iguala o valor recebido ao valor presente das parcelas (bisseção)."""
    if net_amount <= 0 or not payments:
        return Decimal("0")

    def present_value(rate: float) -> float:
        return sum(payment / (1 + rate) ** (index + 1) for index, payment in enumerate(payments))

    low, high = 0.0, 1.0
    if present_value(low) <= net_amount:
        return Decimal("0")
    for _ in range(200):
        middle = (low + high) / 2
        if present_value(middle) > net_amount:
            low = middle
        else:
            high = middle
    return to_rate(Decimal(str((low + high) / 2)))


def loan_terms(
    principal: int,
    installment_count: int,
    monthly_interest_rate,
    origination_fee_rate,
    contract_day: date,
    adjust_due_date: Callable[[date], date],
) -> LoanTerms:
    term_days = PERIOD_DAYS * installment_count
    fee_rate = effective_fee_rate(origination_fee_rate, term_days)
    fee_amount = to_cents(Decimal(principal) * fee_rate)
    net_amount = principal - fee_amount

    schedule = price_schedule(principal, monthly_interest_rate, installment_count, contract_day, adjust_due_date)
    cet_monthly = monthly_irr(net_amount, [item.total_amount for item in schedule])
    cet_annual = to_rate((1 + cet_monthly) ** 12 - 1)

    return LoanTerms(
        principal_amount=principal,
        installment_count=installment_count,
        term_days=term_days,
        monthly_interest_rate=to_rate(monthly_interest_rate),
        effective_fee_rate=fee_rate,
        origination_fee_amount=fee_amount,
        net_amount=net_amount,
        effective_cost_monthly=cet_monthly,
        effective_cost_annual=cet_annual,
        installments=schedule,
    )


def prepayment_discount(remaining: int, interest_open: int, monthly_rate, days_ahead: int) -> int:
    """Desconto a valor presente de uma parcela futura, limitado aos juros em aberto."""
    if days_ahead <= 0 or remaining <= 0:
        return 0
    rate = Decimal(str(monthly_rate))
    present_value = Decimal(remaining) / (1 + rate) ** (Decimal(days_ahead) / Decimal(PERIOD_DAYS))
    discount = to_cents(Decimal(remaining) - present_value)
    return max(0, min(discount, interest_open))
