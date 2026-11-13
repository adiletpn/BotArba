"""Команда /live — включить живое табло и уведомления о каждой операции."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import texts
from app.bot.filters import says

router = Router(name="live")


async def _menu(live, telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    board = await live.board_enabled(telegram_id)
    notify = await live.notify_enabled(telegram_id)
    text = texts.LIVE_MENU.format(
        board="включено ✅" if board else "выключено",
        notify="включены ✅" if notify else "выключены",
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📌 Выключить табло" if board else "📌 Включить табло",
            callback_data="live:board",
        )],
        [InlineKeyboardButton(
            text="🔕 Выключить уведомления" if notify else "🔔 Уведомлять о каждой операции",
            callback_data="live:notify",
        )],
    ])
    return text, markup


@router.message(Command("live"))
async def show_live(message: Message, state: FSMContext, live) -> None:
    await state.clear()
    text, markup = await _menu(live, message.chat.id)
    await message.answer(text, reply_markup=markup)


@router.message(StateFilter(None), says(*texts.SAY_LIVE))
async def show_live_by_word(message: Message, state: FSMContext, live) -> None:
    await show_live(message, state, live)


@router.callback_query(F.data.in_({"live:board", "live:notify"}))
async def toggle_live(callback: CallbackQuery, live) -> None:
    telegram_id = callback.from_user.id
    if callback.data == "live:board":
        if await live.board_enabled(telegram_id):
            await live.disable_board(telegram_id)
            await callback.answer("Табло выключено")
        else:
            await live.enable_board(telegram_id)
            await callback.answer("Табло закреплено вверху чата")
    else:
        on = not await live.notify_enabled(telegram_id)
        await live.set_notify(telegram_id, on)
        await callback.answer("Уведомления включены" if on else "Уведомления выключены")

    text, markup = await _menu(live, telegram_id)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
