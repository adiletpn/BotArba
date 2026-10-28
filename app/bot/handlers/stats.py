"""Кнопка «📈 Статистика» — пользователи и заказы приложения ArbaFood."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot import keyboards, texts
from app.bot.filters import says
from app.bot.render import as_pre
from app.clock import today_local
from app.services.app_stats import StatsError, capture_stats, render_stats

router = Router(name="stats")


async def stats_text(repo, settings, local_day: str) -> str:
    """Посчитать статистику, сохранить снимок и отрендерить.

    Общая точка для кнопки и рассылки. Снимок сохраняется каждый раз: из
    таких снимков и складывается история «активных» в Google Таблице.
    """
    stats = await capture_stats(repo, settings, local_day)
    return render_stats(stats)


@router.message(F.text == texts.BTN_STATS)
@router.message(Command("stats"))
async def show_stats(message: Message, state: FSMContext, repo, settings) -> None:
    await state.clear()
    if not settings.stats_enabled:
        await message.answer(texts.STATS_DISABLED, reply_markup=keyboards.main_keyboard())
        return

    # Выборка идёт ~3 секунды — показываем, что бот не завис.
    notice = await message.answer(texts.STATS_LOADING)
    try:
        text = await stats_text(repo, settings, today_local(settings.timezone))
    except StatsError:
        await notice.edit_text(texts.STATS_FAILED)
        return
    await notice.edit_text(as_pre(text), parse_mode="HTML")


@router.message(StateFilter(None), says(*texts.SAY_STATS))
async def show_stats_by_word(message: Message, state: FSMContext, repo, settings) -> None:
    await show_stats(message, state, repo, settings)
