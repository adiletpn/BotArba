"""Точка входа: бот + вебхук-сервер + планировщик в одном процессе."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiohttp import web

from app.bot.factory import create_bot, create_dispatcher
from app.config import ConfigError, Settings, load_settings
from app.db.database import Database
from app.db.repo import Repo
from app.scheduler import create_scheduler
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
    await repo.ensure_owners(settings.owner_ids)
    logger.info("Белый список: %s", ", ".join(map(str, settings.owner_ids)))
    return db, repo


async def run(settings: Settings) -> None:
    db, repo = await prepare_database(settings)
    bot = create_bot(settings.bot_token)
    dispatcher = create_dispatcher(repo, settings)

    runner = web.AppRunner(create_app(repo, settings))
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

    scheduler = create_scheduler(bot, db, repo, settings)
    scheduler.start()

    try:
        # Накопленные за простой апдейты пропускаем: отвечать на расход,
        # введённый три дня назад, уже бессмысленно.
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot, repo=repo, settings=settings)
    finally:
        logger.info("Останов: закрываю планировщик, сервер и базу")
        scheduler.shutdown(wait=False)
        await runner.cleanup()
        await bot.session.close()
        await db.close()


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
