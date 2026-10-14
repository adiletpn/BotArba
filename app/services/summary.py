"""Сводка за день — то, что бот показывает по кнопке «Баланс» и вечером.

Формат зафиксирован в ТЗ до пробелов, поэтому рендер отделён от сборки данных
и покрыт тестом на точное совпадение с образцом.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DaySummary:
    local_date: str

    opening: int                      # остаток на начало дня, тиыны
    income: int                       # поступления за день (минус возвраты)
    income_count: int                 # «(12 оплат)»
    refund_count: int
    expenses: int                     # отрицательное число
    corrections: int                  # может быть любого знака
    balance: int                      # баланс сейчас

    expense_rows: tuple[tuple[str, int], ...] = ()

    #: False, если ApiPay не ответил при формировании сводки. Сводку всё равно
    #: отправляем — с пометкой о времени последней успешной синхронизации.
    apipay_fresh: bool = True
    last_sync: datetime | None = None


async def build_day_summary(
    repo,
    local_date: str,
    *,
    apipay_fresh: bool = True,
) -> DaySummary:
    """Собрать сводку за день из агрегатов по таблице операций.

    Баланс берём отдельным запросом, а не как opening + income + expenses:
    так расхождение между дневным срезом и общим балансом стало бы видно,
    вместо того чтобы быть замазанным арифметикой.
    """
    totals = await repo.day_totals(local_date)
    opening = await repo.balance_before(local_date)
    balance = await repo.balance()
    rows = await repo.day_expenses_by_category(local_date)
    last_sync = await repo.get_last_apipay_sync()

    return DaySummary(
        local_date=local_date,
        opening=opening,
        income=totals["income"],
        income_count=totals["income_count"],
        refund_count=totals["refund_count"],
        expenses=totals["expense"],
        corrections=totals["correction"],
        balance=balance,
        expense_rows=tuple(rows),
        apipay_fresh=apipay_fresh,
        last_sync=last_sync,
    )


def _plural_payments(count: int) -> str:
    """«1 оплата», «2 оплаты», «12 оплат» — русские формы числительных."""
    if count % 10 == 1 and count % 100 != 11:
        return "оплата"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "оплаты"
    return "оплат"
