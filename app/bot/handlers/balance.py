"""Кнопка «Баланс» — сводка за сегодня."""

from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot import keyboards, texts
from app.bot.filters import says
from app.bot.render import as_pre
from app.clock import now_utc
from app.services.summary import build_day_summary, render_summary

router = Router(name="balance")

#: Сверка идёт раз в час. Если последняя успешная старше этого, данные ApiPay
#: считаем несвежими и показываем пометку из ТЗ.
STALE_AFTER = timedelta(minutes=90)


#: До этого часа сводка считается отчётом за ВЧЕРАШНИЙ день.
#: Нужно для ночного времени рассылки: в 00:00 сегодняшний день пуст,
#: и сводка «за сегодня» показала бы одни нули вместо итогов смены.
NIGHT_REPORT_BEFORE_HOUR = 5


def report_date(now_local, tz) -> str:
    """За какой день отчитываемся, если сводка уходит прямо сейчас."""
    from app.clock import local_date_of, shift_local_date

    today = local_date_of(now_local, tz)
    if now_local.astimezone(tz).hour < NIGHT_REPORT_BEFORE_HOUR:
        return shift_local_date(today, -1)
    return today


async def summary_text(repo, settings, local_date: str | None = None) -> str:
    """Собрать и отрендерить сводку за сегодня.

    Общая точка для кнопки «Баланс» и вечерней рассылки: формат обязан
    совпадать, и дублировать его в двух местах нельзя.
    """
    last_sync = await repo.get_last_apipay_sync()
    if not settings.apipay_enabled:
        # ApiPay не подключён — учёт чисто ручной, пометка про него бессмысленна.
        fresh = True
    else:
        fresh = last_sync is not None and (now_utc() - last_sync) <= STALE_AFTER

    day = local_date or report_date(now_utc(), settings.timezone)
    summary = await build_day_summary(repo, day, apipay_fresh=fresh)
    return render_summary(summary, settings.timezone)


@router.message(F.text == texts.BTN_BALANCE)
@router.message(Command("balance"))
async def show_balance(message: Message, state: FSMContext, repo, settings) -> None:
    # Кнопка работает всегда, в том числе посреди незаконченного диалога —
    # иначе из него было бы не выйти, кроме как «Отменой».
    await state.clear()
    await message.answer(
        as_pre(await summary_text(repo, settings)),
        parse_mode="HTML",
        reply_markup=keyboards.main_keyboard(),
    )


@router.message(StateFilter(None), says(*texts.SAY_BALANCE))
async def show_balance_by_word(message: Message, state: FSMContext, repo, settings) -> None:
    """«баланс» словом. Только вне диалога: внутри это может быть статья расхода."""
    await show_balance(message, state, repo, settings)
