"""Кнопка «История» — последние 10 операций."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.bot import keyboards, texts
from app.bot.render import as_pre
from app.money import format_delta

router = Router(name="history")

HISTORY_LIMIT = 10

#: Как подписывать тип операции в истории.
TYPE_LABELS = {
    "start": "Старт",
    "income": "Поступление",
    "expense": "Расход",
    "correction": "Корректировка",
    "refund": "Возврат",
}


@router.message(F.text == texts.BTN_HISTORY)
async def show_history(message: Message, repo, settings) -> None:
    operations = await repo.recent_operations(HISTORY_LIMIT)
    if not operations:
        await message.answer(texts.HISTORY_EMPTY, reply_markup=keyboards.main_keyboard())
        return

    lines = [texts.HISTORY_HEADER, ""]
    for operation in operations:
        when = operation.occurred_at.astimezone(settings.timezone).strftime("%d.%m %H:%M")
        label = TYPE_LABELS.get(operation.type, operation.type)
        detail = operation.category or operation.comment or ""
        if operation.source == "apipay" and not detail:
            detail = "Kaspi / ApiPay"

        row = f"{when}  {format_delta(operation.amount):>14}  {label}"
        if detail:
            row += f" — {detail}"
        if operation.is_cancelled:
            row += "  (отменено)"
        lines.append(row)

    await message.answer(
        as_pre("\n".join(lines)),
        parse_mode="HTML",
        reply_markup=keyboards.main_keyboard(),
    )
