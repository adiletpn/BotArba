"""/start и ввод стартовой суммы."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards, texts
from app.bot.filters import not_command
from app.bot.states import StartBalance
from app.clock import format_date_ru, today_local
from app.money import AmountError, format_tenge, tiyn_from_user

logger = logging.getLogger(__name__)
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, repo, settings) -> None:
    """Поздороваться и, если стартовой суммы ещё нет, попросить её."""
    await state.clear()
    await message.answer(
        texts.START_GREETING,
        parse_mode="HTML",
        reply_markup=keyboards.main_keyboard(),
    )

    if await repo.has_start_balance():
        return

    await state.set_state(StartBalance.waiting_amount)
    await message.answer(texts.ASK_START_BALANCE, parse_mode="HTML")


@router.message(StartBalance.waiting_amount, not_command)
async def start_balance_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = tiyn_from_user(message.text or "")
    except AmountError as exc:
        await message.answer(texts.BAD_AMOUNT.format(reason=exc), parse_mode="HTML")
        return

    await state.update_data(amount=amount)
    await state.set_state(StartBalance.waiting_confirm)
    await message.answer(
        texts.CONFIRM_START_BALANCE.format(amount=format_tenge(amount)),
        parse_mode="HTML",
        reply_markup=keyboards.confirm_keyboard(),
    )


@router.callback_query(F.data == "start_balance:no", StartBalance.waiting_confirm)
async def start_balance_retry(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(StartBalance.waiting_amount)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.ASK_START_BALANCE, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "start_balance:yes", StartBalance.waiting_confirm)
async def start_balance_confirm(
    callback: CallbackQuery, state: FSMContext, repo, settings, user_id: int
) -> None:
    data = await state.get_data()
    amount = int(data.get("amount") or 0)
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)

    if not amount:
        await callback.answer()
        return

    operation_id = await repo.set_start_balance(amount, created_by=user_id)
    if operation_id is None:
        # Между вводом и подтверждением стартовую сумму уже зафиксировали
        # (например, со второго устройства) — молча не перезаписываем.
        await callback.message.answer(texts.START_BALANCE_EXISTS)
        await callback.answer()
        return

    logger.info("Стартовый баланс зафиксирован: %s тиын", amount)
    await callback.message.answer(
        texts.START_BALANCE_SAVED.format(
            amount=format_tenge(amount),
            date=format_date_ru(today_local(settings.timezone)),
        ),
        parse_mode="HTML",
        reply_markup=keyboards.main_keyboard(),
    )
    await callback.answer()
