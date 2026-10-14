"""Клавиатуры.

Всё управление — постоянная reply-клавиатура с тремя кнопками (требование ТЗ).
Inline-кнопки используются только там, где нужна привязка к конкретной
операции: «Отменить» под расходом.
"""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.bot import texts


def main_keyboard() -> ReplyKeyboardMarkup:
    """Постоянная клавиатура: Баланс, Расход, История."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.BTN_BALANCE)],
            [KeyboardButton(text=texts.BTN_EXPENSE), KeyboardButton(text=texts.BTN_HISTORY)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def categories_keyboard(names: list[str]) -> ReplyKeyboardMarkup:
    """Статьи расхода по две в ряд + «Отмена».

    Список приходит из базы, а не из константы: статью, введённую текстом,
    бот запоминает, и в следующий раз она уже кнопка.
    """
    rows = [
        [KeyboardButton(text=name) for name in names[index:index + 2]]
        for index in range(0, len(names), 2)
    ]
    rows.append([KeyboardButton(text=texts.BTN_CANCEL_INPUT)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура на время ввода суммы: только выход из диалога."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=texts.BTN_CANCEL_INPUT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def undo_keyboard(operation_id: int) -> InlineKeyboardMarkup:
    """Кнопка «Отменить» под подтверждением расхода.

    Живёт 10 минут (настраивается). Срок проверяется при НАЖАТИИ по времени
    операции в базе: кнопка в старом сообщении останется нажимаемой навсегда,
    и единственная надёжная проверка — серверная.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=texts.BTN_UNDO, callback_data=f"undo:{operation_id}")
        ]]
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    """Да/нет под стартовой суммой — её задают один раз, цена ошибки высокая."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="start_balance:yes"),
            InlineKeyboardButton(text="✖️ Заново", callback_data="start_balance:no"),
        ]]
    )
