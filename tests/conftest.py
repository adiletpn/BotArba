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
