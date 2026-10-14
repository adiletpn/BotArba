"""Подключение к SQLite и инициализация схемы."""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    """Тонкая обёртка над одним соединением aiosqlite.

    Бот обслуживает 1-2 пользователя, конкуренция минимальна, поэтому пул
    соединений не нужен. WAL включён в schema.sql, так что вебхук-сервер и
    планировщик пишут параллельно с ботом без блокировок на чтении.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База не открыта: вызовите await db.connect()")
        return self._conn

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        # Ждём до 5 секунд, если другой писатель держит базу, вместо немедленного
        # "database is locked": вебхук и вечерняя сводка могут совпасть по времени.
        await self._conn.execute("PRAGMA busy_timeout = 5000")
        await self._conn.execute("PRAGMA foreign_keys = ON")
        logger.info("База открыта: %s", self._path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def init_schema(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        await self.conn.executescript(sql)
        await self.conn.commit()
        logger.info("Схема применена")

    async def backup_to(self, target: Path) -> Path:
        """Снять консистентную копию базы.

        sqlite3 backup API копирует базу на горячую, не ломаясь о WAL —
        в отличие от простого cp файла .db.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(target) as dest:
            await self.conn.backup(dest)
        return target
