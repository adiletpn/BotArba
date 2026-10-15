"""Настройки: просмотр и смена времени вечерней сводки.

ТЗ: «Время меняется в настройках». Значение лежит в таблице settings, а не
только в .env, поэтому меняется на лету — без редеплоя и перезапуска.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.types import Message

from app.bot import keyboards, texts
from app.bot.filters import says
from app.clock import format_time_local
from app.scheduler import reschedule_summary

logger = logging.getLogger(__name__)
router = Router(name="settings")


def _parse_time(raw: str) -> tuple[int, int] | None:
    parts = raw.strip().replace(".", ":").split(":")
    if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


@router.message(Command("settings"))
@router.message(StateFilter(None), says(*texts.SAY_SETTINGS))
async def show_settings(message: Message, repo, settings) -> None:
    hour, minute = await repo.get_summary_time(
        (settings.summary_hour, settings.summary_minute)
    )
    last_sync = await repo.get_last_apipay_sync()

    await message.answer(
        texts.SETTINGS_VIEW.format(
            summary_time=f"{hour:02d}:{minute:02d}",
            timezone=settings.timezone_name,
            last_sync=(
                format_time_local(last_sync, settings.timezone) if last_sync else "не было"
            ),
        ),
        parse_mode="HTML",
        reply_markup=keyboards.main_keyboard(),
    )


@router.message(Command("settime"))
async def set_summary_time(
    message: Message, command: CommandObject, repo, settings, scheduler=None
) -> None:
    """Сменить время вечерней сводки.

    Планировщик переносится немедленно. scheduler может быть None в тестах и
    при запуске без планировщика — тогда новое время применится при старте.
    """
    parsed = _parse_time(command.args or "")
    if parsed is None:
        await message.answer(texts.SETTIME_USAGE, parse_mode="HTML")
        return

    hour, minute = parsed
    await repo.set_summary_time(hour, minute)

    if scheduler is not None:
        reschedule_summary(scheduler, hour, minute, settings.timezone)

    logger.info("Время сводки изменено на %02d:%02d", hour, minute)
    await message.answer(
        texts.SETTIME_DONE.format(
            summary_time=f"{hour:02d}:{minute:02d}", timezone=settings.timezone_name
        ),
        parse_mode="HTML",
        reply_markup=keyboards.main_keyboard(),
    )


@router.message(Command("export"))
@router.message(StateFilter(None), says(*texts.SAY_EXPORT))
async def export_now(message: Message, repo, settings) -> None:
    """Выгрузить в Google Таблицы немедленно.

    Обычно выгрузка идёт сама после каждой операции, но команда нужна:
    после долгой недоступности Google владельцу важно увидеть результат
    сразу, а не ждать следующего планового запуска.
    """
    if not settings.sheets_enabled:
        await message.answer(texts.EXPORT_DISABLED)
        return

    from app.services.sheets import build_snapshot, push_snapshot

    notice = await message.answer(texts.EXPORT_RUNNING)
    snapshot = await build_snapshot(repo, settings.timezone)

    if await push_snapshot(settings, snapshot):
        await notice.edit_text(
            texts.EXPORT_DONE.format(
                operations=len(snapshot["operations"]["rows"]),
                days=len(snapshot["daily"]["rows"]),
            )
        )
    else:
        await notice.edit_text(texts.EXPORT_FAILED)
