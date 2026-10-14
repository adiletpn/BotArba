"""/whoami и ответ на всё непонятое."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot import keyboards, texts

router = Router(name="misc")


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    """Напомнить, что умеет бот, не перезапуская диалог со /start."""
    await message.answer(
        texts.CAPABILITIES, parse_mode="HTML", reply_markup=keyboards.main_keyboard()
    )


@router.message(Command("whoami"))
async def whoami(message: Message) -> None:
    """Подсказать Telegram ID — им заполняется OWNER_TELEGRAM_IDS."""
    await message.answer(
        texts.WHOAMI.format(telegram_id=message.from_user.id), parse_mode="HTML"
    )


@router.message(F.text)
async def fallback(message: Message) -> None:
    """Последний хендлер: вернуть клавиатуру, если она потерялась.

    Регистрируется после всех остальных, иначе перехватывал бы шаги диалогов.
    """
    await message.answer(texts.UNKNOWN_INPUT, reply_markup=keyboards.main_keyboard())
