"""Запросы к базе.

Все суммы — тиыны со знаком. Баланс нигде не кэшируется: каждая цифра
в интерфейсе — это агрегат по таблице operations, как требует ТЗ.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.clock import local_date_of, now_utc, to_utc_text
from app.db.database import Database
from app.db.models import Operation, OperationSource, OperationType

logger = logging.getLogger(__name__)


class Repo:
    def __init__(self, db: Database, tz: ZoneInfo) -> None:
        self._db = db
        self._tz = tz

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    # ---------- users / белый список ----------

    async def ensure_owners(self, owner_ids: tuple[int, ...]) -> None:
        """Синхронизировать белый список из .env в таблицу users.

        .env — источник истины для доступа: добавить владельца = изменить
        переменную и перезапустить. Существующие строки не трогаем, чтобы
        не терять имя и дату появления.
        """
        now = to_utc_text(now_utc())
        for telegram_id in owner_ids:
            await self._db.conn.execute(
                """
                INSERT INTO users (telegram_id, name, role, created_at)
                VALUES (?, '', 'owner', ?)
                ON CONFLICT (telegram_id) DO UPDATE SET role = 'owner'
                """,
                (telegram_id, now),
            )
        await self._db.conn.commit()

    async def is_allowed(self, telegram_id: int) -> bool:
        async with self._db.conn.execute(
            "SELECT 1 FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def remember_name(self, telegram_id: int, name: str) -> None:
        await self._db.conn.execute(
            "UPDATE users SET name = ? WHERE telegram_id = ? AND name <> ?",
            (name, telegram_id, name),
        )
        await self._db.conn.commit()

    async def owner_ids(self) -> list[int]:
        """Кому рассылать вечернюю сводку."""
        async with self._db.conn.execute(
            "SELECT telegram_id FROM users ORDER BY telegram_id"
        ) as cursor:
            return [row["telegram_id"] for row in await cursor.fetchall()]
