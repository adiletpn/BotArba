"""Планировщик: вечерняя сводка, часовая сверка, ежедневный бэкап.

Все расписания живут в зоне мерчанта (Asia/Almaty): «21:00» в ТЗ — это
местное время, а не UTC.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.apipay.client import ApiPayClient
from app.bot.handlers.balance import summary_text
from app.bot.render import as_pre
from app.services.backup import make_backup
from app.services.sync import reconcile

logger = logging.getLogger(__name__)


async def run_sync(repo, settings) -> None:
    """Часовая сверка с ApiPay."""
    if not settings.apipay_enabled:
        return
    async with ApiPayClient(settings.apipay_api_key, settings.apipay_base_url) as client:
        result = await reconcile(repo, client, settings)
    if result.ok:
        logger.info(
            "Сверка: счетов %s, новых поступлений %s, возвратов %s",
            result.invoices_seen, result.income_added, result.refunds_added,
        )


async def send_evening_summary(bot, repo, settings) -> None:
    """Разослать сводку за день владельцам.

    Перед отправкой — ещё одна сверка, как требует ТЗ. Если ApiPay не ответил,
    сводка всё равно уходит: пометку о времени последней синхронизации
    добавляет сам рендер.
    """
    await run_sync(repo, settings)

    text = as_pre(await summary_text(repo, settings))
    for telegram_id in await repo.owner_ids():
        try:
            await bot.send_message(telegram_id, text, parse_mode="HTML")
        except Exception:
            # Один заблокировавший бота владелец не должен ломать рассылку остальным.
            logger.exception("Не удалось отправить сводку пользователю %s", telegram_id)
    logger.info("Вечерняя сводка отправлена")


async def run_sheets_sync(repo, settings) -> None:
    """Периодическая выгрузка в таблицу — страховка на случай, когда
    фоновая задача не смогла отправить снимок (Google был недоступен)."""
    from app.services.sheets import sync

    if not settings.sheets_enabled:
        return
    try:
        await sync(repo, settings)
    except Exception:
        logger.exception("Плановая выгрузка в Google Таблицы сорвалась")


async def run_backup(db, settings) -> None:
    try:
        await make_backup(db, settings.backup_dir, settings.backup_keep_days)
    except Exception:
        logger.exception("Бэкап не удался")


SUMMARY_JOB_ID = "evening_summary"


async def create_scheduler(bot, db, repo, settings) -> AsyncIOScheduler:
    """Собрать планировщик.

    Время сводки читается из НАСТРОЕК В БАЗЕ, а не из окружения: ТЗ требует,
    чтобы его можно было менять без редеплоя (команда /settime).

    coalesce + misfire_grace_time нужны потому, что контейнер на Railway
    может быть перезапущен: пропущенный запуск должен выполниться один раз
    при старте, а не N раз подряд и не потеряться совсем.
    """
    summary_hour, summary_minute = await repo.get_summary_time(
        (settings.summary_hour, settings.summary_minute)
    )
    scheduler = AsyncIOScheduler(
        timezone=settings.timezone,
        job_defaults={"coalesce": True, "misfire_grace_time": 3600, "max_instances": 1},
    )

    scheduler.add_job(
        send_evening_summary,
        CronTrigger(hour=summary_hour, minute=summary_minute),
        args=(bot, repo, settings),
        id=SUMMARY_JOB_ID,
        name="Вечерняя сводка",
    )

    # Сверка в :05, чтобы не совпадать с вечерней сводкой, которая синхронизируется сама.
    scheduler.add_job(
        run_sync,
        CronTrigger(minute=5),
        args=(repo, settings),
        id="hourly_sync",
        name="Часовая сверка с ApiPay",
    )

    if settings.sheets_enabled:
        scheduler.add_job(
            run_sheets_sync,
            CronTrigger(minute=f"*/{settings.sheets_sync_minutes}"),
            args=(repo, settings),
            id="sheets_sync",
            name="Выгрузка в Google Таблицы",
        )

    scheduler.add_job(
        run_backup,
        CronTrigger(hour=3, minute=30),
        args=(db, settings),
        id="daily_backup",
        name="Ежедневный бэкап базы",
    )

    logger.info(
        "Планировщик: сводка в %02d:%02d (%s), сверка каждый час, бэкап в 03:30",
        summary_hour, summary_minute, settings.timezone_name,
    )
    return scheduler


def reschedule_summary(scheduler: AsyncIOScheduler, hour: int, minute: int) -> None:
    """Перенести вечернюю сводку на новое время без перезапуска процесса."""
    scheduler.reschedule_job(
        SUMMARY_JOB_ID, trigger=CronTrigger(hour=hour, minute=minute)
    )
    logger.info("Вечерняя сводка перенесена на %02d:%02d", hour, minute)
