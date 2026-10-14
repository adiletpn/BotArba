"""/start и ввод стартовой суммы."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards, texts
from app.bot.states import StartBalance
from app.clock import format_date_ru, today_local
from app.money import AmountError, format_tenge, tiyn_from_user

logger = logging.getLogger(__name__)
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, repo, settings) -> None:
    """Поздороваться и, если стартовой суммы ещё нет, попросить её."""
    await state.clear()
    await message.answer(texts.START_GREETING, reply_markup=keyboards.main_keyboard())

    if await repo.has_start_balance():
        return

    await state.set_state(StartBalance.waiting_amount)
    await message.answer(texts.ASK_START_BALANCE, parse_mode="HTML")
