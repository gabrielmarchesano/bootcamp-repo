"""Em que fatura cai uma compra — conta pura, sem banco.

Convenção do time (a mesma da maioria dos emissores):
  • compra ANTES do dia de fechamento cai na fatura que fecha neste mês;
    no dia do fechamento ou depois, cai na do mês seguinte ("melhor dia
    de compra" = dia do fechamento);
  • o vencimento é o primeiro `due_day` DEPOIS do fechamento;
  • parcela k (1, 2, …) cai k−1 meses depois da primeira.
O ajuste do vencimento para dia útil é do controller, que pergunta ao
banco (tabela holiday).
"""

from datetime import date
from typing import Tuple


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    return date(day.year + month_index // 12, month_index % 12 + 1, day.day)


def closing_date_for(purchase_date: date, closing_day: int) -> date:
    this_month = purchase_date.replace(day=closing_day)
    if purchase_date < this_month:
        return this_month
    return add_months(this_month, 1)


def due_date_after(closing_date: date, due_day: int) -> date:
    candidate = closing_date.replace(day=due_day)
    if candidate > closing_date:
        return candidate
    return add_months(candidate, 1)


def cycle_for(purchase_date: date, closing_day: int, due_day: int, installment_number: int = 1) -> Tuple[date, date]:
    """(fechamento, vencimento) da fatura que recebe a parcela."""
    closing = add_months(closing_date_for(purchase_date, closing_day), installment_number - 1)
    return closing, due_date_after(closing, due_day)


def split_installments(amount: int, installment_count: int):
    """Divide em parcelas inteiras; o resto dos centavos vai na primeira."""
    base = amount // installment_count
    first = amount - base * (installment_count - 1)
    return [first] + [base] * (installment_count - 1)
