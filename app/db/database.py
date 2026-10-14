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
