"""Кнопка «Отменить» под расходом."""

from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot import texts
from app.clock import now_utc
from app.money import format_tenge

logger = logging.getLogger(__name__)
router = Router(name="undo")


@router.callback_query(F.data.startswith("undo:"))
async def undo_operation(callback: CallbackQuery, repo, settings) -> None:
    """Отменить операцию, если окно ещё не вышло.

    Срок считаем от времени записи операции, а не от возраста сообщения:
    кнопка в истории чата остаётся нажимаемой сколько угодно, поэтому
    проверка обязана быть серверной.
    """
    _, _, raw_id = (callback.data or "").partition(":")
    if not raw_id.isdigit():
        await callback.answer()
        return

    operation = await repo.get_operation(int(raw_id))
    if operation is None:
        await callback.answer(texts.UNKNOWN_INPUT, show_alert=True)
        return

    if operation.is_cancelled:
        await callback.answer(texts.UNDO_ALREADY, show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    window = timedelta(minutes=settings.undo_window_minutes)
    if now_utc() - operation.created_at > window:
        await callback.answer(
            texts.UNDO_EXPIRED.format(minutes=settings.undo_window_minutes),
            show_alert=True,
        )
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    if not await repo.cancel_operation(operation.id):
        await callback.answer(texts.UNDO_ALREADY, show_alert=True)
        return

    balance = await repo.balance()
    logger.info("Операция %s отменена, баланс %s тиын", operation.id, balance)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        texts.UNDO_DONE.format(balance=format_tenge(balance)), parse_mode="HTML"
    )
    await callback.answer()
