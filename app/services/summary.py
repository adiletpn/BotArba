"""Сводка за день — то, что бот показывает по кнопке «Баланс» и вечером.

Формат зафиксирован в ТЗ до пробелов, поэтому рендер отделён от сборки данных
и покрыт тестом на точное совпадение с образцом.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    opening = await repo.opening_balance(local_date)
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


#: Ширина колонки с подписью, чтобы суммы выстроились в столбик.
#: Работает только в монospace-блоке — рендер оборачивается в <pre>.
_LABEL_WIDTH = 17


def _row(label: str, value: str) -> str:
    return f"{label:<{_LABEL_WIDTH}}{value}"


def render_summary(summary: DaySummary, tz) -> str:
    """Отрендерить сводку по образцу из ТЗ.

    Возвращает ТЕКСТ БЕЗ HTML-обёртки: оборачивание в <pre> и экранирование —
    задача отправителя, который знает parse_mode.
    """
    from app.clock import format_date_ru, format_time_local
    from app.money import format_delta, format_tenge

    lines = [f"📊 Сводка за {format_date_ru(summary.local_date)}", ""]
    lines.append(_row("На начало дня:", format_tenge(summary.opening)))

    income_line = format_delta(summary.income)
    if summary.income_count:
        income_line += f"  ({summary.income_count} {_plural_payments(summary.income_count)})"
    lines.append(_row("Поступления:", income_line))

    lines.append(_row("Расходы:", format_delta(summary.expenses)))
    for name, amount in summary.expense_rows:
        lines.append(f"  • {name} — {format_tenge(abs(amount))}")

    if summary.corrections:
        lines.append(_row("Корректировки:", format_delta(summary.corrections)))
    if summary.refund_count:
        lines.append(_row("Возвраты:", f"{summary.refund_count} шт. (учтены в поступлениях)"))

    lines.append("")
    lines.append(_row("Баланс сейчас:", format_tenge(summary.balance)))

    if not summary.apipay_fresh:
        when = format_time_local(summary.last_sync, tz) if summary.last_sync else "неизвестно"
        lines.append("")
        lines.append(f"⚠️ Данные ApiPay обновлены в {when}")

    return "\n".join(lines)
