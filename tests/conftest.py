from zoneinfo import ZoneInfo

import pytest_asyncio

from app.db.database import Database
from app.db.repo import Repo

ALMATY = ZoneInfo("Asia/Almaty")

#: Владелец, от имени которого тесты пишут операции.
OWNER_ID = 1


@pytest_asyncio.fixture
async def repo(tmp_path):
    """Чистая база на каждый тест — в файле, а не в :memory:.

    Файл проверяет и реальный путь с mkdir, и WAL из schema.sql, которые
    в in-memory базе ведут себя иначе, чем в бою.
    """
    db = Database(tmp_path / "test.db")
    await db.connect()
    await db.init_schema()
    repo = Repo(db, ALMATY)
    await repo.seed_categories()
    # operations.created_by ссылается на users: без владельца в базе любая
    # запись от пользователя упадёт на FOREIGN KEY — как и в бою до ensure_owners().
    await repo.ensure_owners((OWNER_ID,))
    try:
        yield repo
    finally:
        await db.close()


@pytest_asyncio.fixture
async def settings(tmp_path):
    """Настройки для тестов — собираются напрямую, без .env."""
    from pathlib import Path

    from app.config import Settings

    return Settings(
        bot_token="123:TEST",
        owner_ids=(OWNER_ID,),
        apipay_api_key="test-key",
        apipay_webhook_secret="whsec_test",
        apipay_base_url="https://api.apipay.kz/api/v1",
        apipay_sandbox=True,
        apipay_webhook_path="apipay",
        db_path=tmp_path / "test.db",
        timezone=ALMATY,
        timezone_name="Asia/Almaty",
        summary_hour=21,
        summary_minute=0,
        web_host="127.0.0.1",
        web_port=0,
        sync_window_days=2,
        undo_window_minutes=10,
        backup_dir=Path(tmp_path / "backups"),
        backup_keep_days=14,
    )
