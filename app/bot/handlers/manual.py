"""Ручные операции: /income и /correct.

Нужны потому, что ApiPay видит не все деньги: наличные, переводы на карту и
продажи мимо счетов ApiPay приходится вносить руками.
"""

from __future__ import annotations

import logging
import re

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot import keyboards, texts
from app.bot.filters import not_command, says
from app.bot.states import Correction, ManualIncome
from app.money import AmountError, format_tenge, tiyn_from_user

logger = logging.getLogger(__name__)
router = Router(name="manual")

SKIP_COMMENT = {"-", "–", "нет", "без комментария"}


@router.message(Command("income"))
@router.message(StateFilter(None), says(*texts.SAY_INCOME))
async def income_start(message: Message, state: FSMContext) -> None:
    await state.set_state(ManualIncome.waiting_amount)
    await message.answer(texts.ASK_INCOME_AMOUNT, reply_markup=keyboards.cancel_keyboard())


@router.message(ManualIncome.waiting_amount, not_command)
async def income_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = tiyn_from_user(message.text or "")
    except AmountError as exc:
        await message.answer(texts.BAD_AMOUNT.format(reason=exc), parse_mode="HTML")
        return

    await state.update_data(amount=amount)
    await state.set_state(ManualIncome.waiting_comment)
    await message.answer(
        texts.ASK_INCOME_COMMENT.format(amount=format_tenge(amount)), parse_mode="HTML"
    )


@router.message(ManualIncome.waiting_comment, not_command)
async def income_comment(message: Message, state: FSMContext, repo, user_id: int) -> None:
    comment = (message.text or "").strip()
    if comment.lower() in SKIP_COMMENT:
        comment = ""

    data = await state.get_data()
    amount = int(data.get("amount") or 0)
    await state.clear()

    await repo.add_operation(
        type="income", amount=amount, comment=comment or "Ручное поступление",
        source="manual", created_by=user_id,
    )
    balance = await repo.balance()
    logger.info("Ручное поступление %s тиын", amount)

    await message.answer(
        texts.INCOME_SAVED.format(
            amount=format_tenge(amount), comment=comment or "без комментария",
            balance=format_tenge(balance),
        ),
        parse_mode="HTML",
        reply_markup=keyboards.main_keyboard(),
    )


#: Корректировка может быть в обе стороны, поэтому знак разбирается отдельно
#: от суммы: tiyn_from_user принципиально не принимает отрицательные значения.
_SIGNED = re.compile(r"^\s*([+−-])?\s*(.+)$", re.DOTALL)


@router.message(Command("correct"))
@router.message(StateFilter(None), says(*texts.SAY_CORRECT))
async def correct_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Correction.waiting_amount)
    await message.answer(
        texts.ASK_CORRECTION_AMOUNT,
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )


@router.message(Correction.waiting_amount, not_command)
async def correction_amount(message: Message, state: FSMContext) -> None:
    match = _SIGNED.match(message.text or "")
    if match is None:
        await message.answer(texts.BAD_AMOUNT.format(reason="пустой ввод"), parse_mode="HTML")
        return

    sign, rest = match.group(1), match.group(2)
    try:
        amount = tiyn_from_user(rest)
    except AmountError as exc:
        await message.answer(texts.BAD_AMOUNT.format(reason=exc), parse_mode="HTML")
        return

    if sign in ("-", "−"):
        amount = -amount

    await state.update_data(amount=amount)
    await state.set_state(Correction.waiting_comment)
    await message.answer(
        texts.ASK_CORRECTION_COMMENT.format(amount=format_tenge(amount)), parse_mode="HTML"
    )


@router.message(Correction.waiting_comment, not_command)
async def correction_comment(message: Message, state: FSMContext, repo, user_id: int) -> None:
    comment = (message.text or "").strip()
    data = await state.get_data()
    amount = int(data.get("amount") or 0)
    await state.clear()

    if not amount:
        await message.answer(texts.UNKNOWN_INPUT, reply_markup=keyboards.main_keyboard())
        return

    await repo.add_operation(
        type="correction", amount=amount,
        comment=comment or "Корректировка без комментария",
        source="manual", created_by=user_id,
    )
    balance = await repo.balance()
    logger.info("Корректировка %s тиын: %s", amount, comment)

    await message.answer(
        texts.CORRECTION_SAVED.format(
            amount=format_tenge(amount), comment=comment or "без комментария",
            balance=format_tenge(balance),
        ),
        parse_mode="HTML",
        reply_markup=keyboards.main_keyboard(),
    )
