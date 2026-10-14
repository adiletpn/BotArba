"""Кнопка «Расход»: сумма -> статья -> подтверждение с «Отменить».

Статьи показываются inline-кнопками, поэтому постоянная клавиатура из трёх
кнопок никуда не девается, а подтверждение расхода приходит одним сообщением
вместе с кнопкой «Отменить» — ровно как в образце ТЗ.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards, texts
from app.bot.filters import says
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
@router.message(Command("expense"))
@router.message(StateFilter(None), says(*texts.SAY_EXPENSE))
async def expense_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Expense.waiting_amount)
    await message.answer(texts.ASK_EXPENSE_AMOUNT, parse_mode="HTML")


@router.message(Expense.waiting_amount)
async def expense_amount(message: Message, state: FSMContext, repo) -> None:
    try:
        amount = tiyn_from_user(message.text or "")
    except AmountError as exc:
        await message.answer(texts.BAD_AMOUNT.format(reason=exc), parse_mode="HTML")
        return

    # Список статей кладём в состояние: кнопки присылают его индекс, и
    # порядок обязан совпасть с тем, что видел пользователь, даже если
    # между шагами кто-то добавил новую статью.
    names = await repo.active_categories()
    await state.update_data(amount=amount, names=names)
    await state.set_state(Expense.waiting_category)
    await message.answer(
        texts.ASK_EXPENSE_CATEGORY.format(amount=format_tenge(amount)),
        parse_mode="HTML",
        reply_markup=keyboards.categories_keyboard(names),
    )


async def _save_expense(
    repo, settings, *, amount: int, category: str, user_id: int
) -> tuple[int, int]:
    """Записать расход и вернуть (id операции, баланс после)."""
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
    return operation_id, balance


def _confirmation(amount: int, category: str, balance: int) -> str:
    return texts.EXPENSE_SAVED.format(
        amount=format_tenge(amount),
        category=category,
        balance=format_tenge(balance),
    )


@router.callback_query(F.data == "cat:cancel", Expense.waiting_category)
async def expense_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(texts.INPUT_CANCELLED)
    await callback.answer()


@router.callback_query(F.data.startswith("cat:"), Expense.waiting_category)
async def expense_category_button(
    callback: CallbackQuery, state: FSMContext, repo, settings, user_id: int
) -> None:
    """Статья выбрана кнопкой.

    Сообщение с выбором статьи превращается в подтверждение с кнопкой
    «Отменить» — так остаётся одно сообщение вместо трёх.
    """
    data = await state.get_data()
    names: list[str] = data.get("names") or []
    _, _, raw_index = (callback.data or "").partition(":")

    if not raw_index.isdigit() or int(raw_index) >= len(names):
        # Нажали кнопку из устаревшего сообщения — список статей уже другой.
        await callback.answer("Начните расход заново", show_alert=True)
        await state.clear()
        return

    amount = int(data.get("amount") or 0)
    await state.clear()
    if not amount:
        await callback.answer()
        return

    category = names[int(raw_index)]
    operation_id, balance = await _save_expense(
        repo, settings, amount=amount, category=category, user_id=user_id
    )
    await callback.message.edit_text(
        _confirmation(amount, category, balance),
        parse_mode="HTML",
        reply_markup=keyboards.undo_keyboard(operation_id),
    )
    await callback.answer()


@router.message(Expense.waiting_category, F.text)
async def expense_category_text(
    message: Message, state: FSMContext, repo, settings, user_id: int
) -> None:
    """Статья введена текстом — ТЗ разрешает и такой ввод."""
    category = (message.text or "").strip()
    data = await state.get_data()
    amount = int(data.get("amount") or 0)
    await state.clear()

    if not amount or not category:
        await message.answer(texts.UNKNOWN_INPUT, reply_markup=keyboards.main_keyboard())
        return

    operation_id, balance = await _save_expense(
        repo, settings, amount=amount, category=category, user_id=user_id
    )
    await message.answer(
        _confirmation(amount, category, balance),
        parse_mode="HTML",
        reply_markup=keyboards.undo_keyboard(operation_id),
    )
