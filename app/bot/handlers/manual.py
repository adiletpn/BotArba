"""Ручные операции: /income и /correct.

Нужны потому, что ApiPay видит не все деньги: наличные, переводы на карту и
продажи мимо счетов ApiPay приходится вносить руками.
"""

from __future__ import annotations

import logging
import re

from aiogram import Router
from aiogram.filters import Command, CommandObject, StateFilter
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
async def income_start(
    message: Message,
    state: FSMContext,
    command: CommandObject | None = None,
    is_admin: bool = True,
) -> None:
    """Начать поступление. С суммой в команде (`/income 50000`) — сразу к комментарию."""
    if not is_admin:
        await message.answer(texts.ADMIN_ONLY)
        return
    if command is not None and command.args:
        try:
            amount = tiyn_from_user(command.args)
        except AmountError as exc:
            await message.answer(texts.BAD_AMOUNT.format(reason=exc), parse_mode="HTML")
            return
        await state.update_data(amount=amount)
        await state.set_state(ManualIncome.waiting_comment)
        await message.answer(
            texts.ASK_INCOME_COMMENT.format(amount=format_tenge(amount)),
            parse_mode="HTML",
        )
        return

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
async def correct_start(
    message: Message,
    state: FSMContext,
    command: CommandObject | None = None,
    is_admin: bool = True,
) -> None:
    """Начать корректировку. С суммой в команде (`/correct +50000`) — сразу к причине."""
    if not is_admin:
        await message.answer(texts.ADMIN_ONLY)
        return
    if command is not None and command.args:
        amount = parse_signed_amount(command.args)
        if amount is None:
            await message.answer(
                texts.BAD_AMOUNT.format(reason="нужно число"), parse_mode="HTML"
            )
            return
        await state.update_data(amount=amount)
        await state.set_state(Correction.waiting_comment)
        await message.answer(
            texts.ASK_CORRECTION_COMMENT.format(amount=format_tenge(amount)),
            parse_mode="HTML",
        )
        return

    await state.set_state(Correction.waiting_amount)
    await message.answer(
        texts.ASK_CORRECTION_AMOUNT,
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )


def parse_signed_amount(raw: str) -> int | None:
    """Разобрать «+50000», «-50000» или «50000».

    Без знака считаем, что имели в виду плюс: человек, набирающий
    «/correct 1050000», хочет добавить деньги, а не получить отказ.
    """
    match = _SIGNED.match(raw or "")
    if match is None:
        return None
    sign, rest = match.group(1), match.group(2)
    try:
        amount = tiyn_from_user(rest)
    except AmountError:
        return None
    return -amount if sign in ("-", "−") else amount


@router.message(Correction.waiting_amount, not_command)
async def correction_amount(message: Message, state: FSMContext) -> None:
    amount = parse_signed_amount(message.text or "")
    if amount is None:
        await message.answer(
            texts.BAD_AMOUNT.format(reason="нужно число, например +50000"),
            parse_mode="HTML",
        )
        return

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


@router.message(Command("reconcile"))
async def reconcile_with_kaspi(
    message: Message,
    state: FSMContext,
    repo,
    user_id: int,
    command: CommandObject | None = None,
    is_admin: bool = True,
) -> None:
    """Сверить баланс с остатком Kaspi: «/reconcile 1663000».

    Остаток счёта ApiPay не отдаёт, поэтому подтянуть его сам бот не может.
    Эта команда — ближайшая замена: человек смотрит цифру в Kaspi Pay, а
    разницу бот считает сам и в ту же секунду. Ручной `/correct` требовал
    вычитать в уме, и именно так 14 октября в баланс попала ошибка.
    """
    if not is_admin:
        await message.answer(texts.ADMIN_ONLY)
        return

    await state.clear()
    raw = command.args if command is not None else ""
    try:
        target = tiyn_from_user(raw or "")
    except AmountError:
        await message.answer(texts.RECONCILE_USAGE, parse_mode="HTML")
        return

    before = await repo.balance()
    delta = await repo.align_balance_to(
        target,
        comment=f"Сверка с Kaspi: на счёте {format_tenge(target)}",
        created_by=user_id,
    )
    if delta is None:
        await message.answer(
            texts.RECONCILE_EQUAL.format(balance=format_tenge(target)), parse_mode="HTML"
        )
        return

    logger.info("Сверка с Kaspi: поправка %s тиын, целевой баланс %s", delta, target)
    sign = "+" if delta > 0 else ""
    await message.answer(
        texts.RECONCILE_DONE.format(
            before=format_tenge(target - delta),
            target=format_tenge(target),
            delta=f"{sign}{format_tenge(delta)}",
        ),
        parse_mode="HTML",
        reply_markup=keyboards.main_keyboard(),
    )
