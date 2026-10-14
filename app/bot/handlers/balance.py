"""Кнопка «Баланс» — сводка за сегодня."""

from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.types import Message

from app.bot import keyboards, texts
from app.bot.render import as_pre
from app.clock import now_utc, today_local
from app.services.summary import build_day_summary, render_summary

router = Router(name="balance")

#: Сверка идёт раз в час. Если последняя успешная старше этого, данные ApiPay
#: считаем несвежими и показываем пометку из ТЗ.
STALE_AFTER = timedelta(minutes=90)


async def summary_text(repo, settings) -> str:
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

    summary = await build_day_summary(
        repo, today_local(settings.timezone), apipay_fresh=fresh
    )
    return render_summary(summary, settings.timezone)


@router.message(F.text == texts.BTN_BALANCE)
async def show_balance(message: Message, repo, settings) -> None:
    await message.answer(
        as_pre(await summary_text(repo, settings)),
        parse_mode="HTML",
        reply_markup=keyboards.main_keyboard(),
    )
