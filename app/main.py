"""Точка входа: бот + вебхук-сервер + планировщик в одном процессе."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiohttp import web

from app.bot.factory import create_bot, create_dispatcher, register_commands
from app.clock import now_utc
from app.config import ConfigError, Settings, load_settings
from app.db.database import Database
from app.db.repo import Repo
from app.scheduler import create_scheduler
from app.services.sheets import SheetsSyncer
from app.web.server import create_app

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    # aiogram на INFO печатает каждый апдейт — для 1-2 пользователей это шум.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors").setLevel(logging.WARNING)


async def prepare_database(settings: Settings) -> tuple[Database, Repo]:
    db = Database(settings.db_path)
    await db.connect()
    await db.init_schema()
    await db.migrate()

    repo = Repo(db, settings.timezone)
    await repo.seed_categories()
    await repo.seed_settings(
        f"{settings.summary_hour:02d}:{settings.summary_minute:02d}",
        settings.timezone_name,
    )
    await repo.ensure_owners(settings.owner_ids)
    logger.info("Белый список: %s", ", ".join(map(str, settings.owner_ids)))
    return db, repo


async def run(settings: Settings) -> None:
    db, repo = await prepare_database(settings)
    bot = create_bot(settings.bot_token)
    dispatcher = create_dispatcher(repo, settings)

    scheduler = await create_scheduler(bot, db, repo, settings)

    runner = web.AppRunner(create_app(repo, settings, scheduler))
    await runner.setup()
    site = web.TCPSite(runner, settings.web_host, settings.web_port)
    await site.start()
    logger.info(
        "Вебхук слушает http://%s:%s%s",
        settings.web_host, settings.web_port, settings.webhook_route,
    )
    if not settings.apipay_enabled:
        logger.warning(
            "APIPAY_API_KEY не задан: поступления Kaspi подтягиваться не будут, "
            "работает только ручной учёт (/income, /correct, расходы)."
        )

    # Выгрузка в Google Таблицы: хендлеры только поднимают флаг, отправляет
    # отдельная задача — чтобы ответ на «Расход» не ждал ответа от Google.
    syncer = SheetsSyncer(repo, settings)
    repo.set_change_listener(syncer.request)
    syncer.start()
    syncer.request()   # первая выгрузка при старте, чтобы таблица догнала базу

    scheduler.start()

    if settings.stats_enabled:
        asyncio.create_task(_backfill_stats(repo, settings), name="stats-backfill")

    # Печатаем ФАКТИЧЕСКОЕ время следующего запуска, а не то, что мы задумали.
    # Пока лог показывал намерение («сводка в 21:00»), он скрывал, что триггер
    # считает время по UTC: расхождение всплыло только сообщением в 02:00.
    for job in sorted(scheduler.get_jobs(), key=lambda j: j.next_run_time or now_utc()):
        if job.next_run_time:
            logger.info(
                "Задание «%s» — следующий запуск %s",
                job.name,
                job.next_run_time.astimezone(settings.timezone).strftime("%d.%m %H:%M %Z"),
            )
    # Хендлер /settime переносит задание на лету — для этого ему нужен сам планировщик.
    dispatcher["scheduler"] = scheduler

    try:
        # Накопленные за простой апдейты пропускаем: отвечать на расход,
        # введённый три дня назад, уже бессмысленно.
        await bot.delete_webhook(drop_pending_updates=True)
        await register_commands(bot)
        await dispatcher.start_polling(bot, repo=repo, settings=settings)
    finally:
        logger.info("Останов: закрываю планировщик, сервер и базу")
        scheduler.shutdown(wait=False)
        repo.set_change_listener(None)
        await syncer.stop()
        await runner.cleanup()
        await bot.session.close()
        await db.close()


async def _backfill_stats(repo, settings) -> None:
    """История статистики ArbaFood за 30 дней — один раз, если её ещё нет."""
    from app.services.app_stats import StatsError, backfill_history

    try:
        await backfill_history(repo, settings)
    except StatsError:
        logger.warning("История статистики ArbaFood не восстановлена, попробую при следующем старте")


def main() -> int:
    setup_logging()
    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error("Конфигурация неверна: %s", exc)
        return 2

    try:
        asyncio.run(run(settings))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановлено пользователем")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
