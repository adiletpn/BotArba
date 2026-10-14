"""Кнопка «Расход»: сумма -> статья -> подтверждение с «Отменить»."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot import keyboards, texts
from app.bot.states import Expense
from app.money import AmountError, format_tenge, tiyn_from_user

logger = logging.getLogger(__name__)
router = Router(name="expense")


@router.message(F.text == texts.BTN_CANCEL_INPUT)
async def cancel_input(message: Message, state: FSMContext) -> None:
    """Выйти из любого диалога ввода, ничего не записав."""
    await state.clear()
    await message.answer(texts.INPUT_CANCELLED, reply_markup=keyboards.main_keyboard())


@router.message(F.text == texts.BTN_EXPENSE)
async def expense_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Expense.waiting_amount)
    await message.answer(
        texts.ASK_EXPENSE_AMOUNT,
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )


@router.message(Expense.waiting_amount)
async def expense_amount(message: Message, state: FSMContext, repo) -> None:
    try:
        amount = tiyn_from_user(message.text or "")
    except AmountError as exc:
        await message.answer(texts.BAD_AMOUNT.format(reason=exc), parse_mode="HTML")
        return

    await state.update_data(amount=amount)
    await state.set_state(Expense.waiting_category)
    await message.answer(
        texts.ASK_EXPENSE_CATEGORY.format(amount=format_tenge(amount)),
        parse_mode="HTML",
        reply_markup=keyboards.categories_keyboard(await repo.active_categories()),
    )


@router.message(Expense.waiting_category, F.text)
async def expense_category(
    message: Message, state: FSMContext, repo, settings, user_id: int
) -> None:
    """Записать расход с выбранной или введённой статьёй.

    Статья приходит либо кнопкой, либо текстом — различать их не нужно:
    любую новую статью запоминаем, чтобы в следующий раз она стала кнопкой.
    """
    category = (message.text or "").strip()
    data = await state.get_data()
    amount = int(data.get("amount") or 0)
    await state.clear()

    if not amount:
        await message.answer(texts.UNKNOWN_INPUT, reply_markup=keyboards.main_keyboard())
        return

    known = await repo.active_categories()
    if category not in known:
        await repo.add_category(category)

    # В базу расход идёт со знаком минус: баланс — это SUM(amount).
    operation_id = await repo.add_operation(
        type="expense",
        amount=-amount,
        category=category,
        source="manual",
        created_by=user_id,
    )
    balance = await repo.balance()
    logger.info("Расход %s тиын, статья %s, id=%s", amount, category, operation_id)

    await message.answer(
        texts.EXPENSE_SAVED.format(
            amount=format_tenge(amount), category=category,
            balance=format_tenge(balance),
        ),
        parse_mode="HTML",
        reply_markup=keyboards.main_keyboard(),
    )
    # Кнопка «Отменить» приходит отдельным сообщением: reply-клавиатуру и
    # inline-кнопку Telegram не разрешает прикрепить к одному сообщению.
    await message.answer(
        f"Отменить можно в течение {settings.undo_window_minutes} минут.",
        reply_markup=keyboards.undo_keyboard(operation_id),
    )
