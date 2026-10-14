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

    # ---------- запись операций ----------

    async def add_operation(
        self,
        *,
        type: OperationType,
        amount: int,
        category: str | None = None,
        comment: str | None = None,
        source: OperationSource = "manual",
        external_id: str | None = None,
        created_by: int | None = None,
        occurred_at: datetime | None = None,
    ) -> int | None:
        """Записать операцию. Вернуть её id, либо None, если она уже есть.

        None возвращается только при конфликте external_id — это нормальный
        путь для повторного вебхука ApiPay, а не ошибка. Сумма приходит уже
        со знаком: вызывающий знает, расход это или поступление.
        """
        moment = occurred_at or now_utc()
        async with self._db.conn.execute(
            """
            INSERT INTO operations (
                type, amount, category, comment, source, external_id,
                created_by, occurred_at, created_at, local_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (external_id) DO NOTHING
            RETURNING id
            """,
            (
                type, amount, category, comment, source, external_id,
                created_by, to_utc_text(moment), to_utc_text(now_utc()),
                local_date_of(moment, self._tz),
            ),
        ) as cursor:
            row = await cursor.fetchone()
        await self._db.conn.commit()

        if row is None:
            logger.info("Операция с external_id=%s уже записана, пропуск", external_id)
            return None
        return int(row["id"])

    async def get_operation(self, operation_id: int) -> Operation | None:
        async with self._db.conn.execute(
            "SELECT * FROM operations WHERE id = ?", (operation_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return Operation.from_row(row) if row else None

    async def cancel_operation(self, operation_id: int) -> bool:
        """Отменить операцию (кнопка «Отменить» под расходом).

        Строка не удаляется и сумма не правится — ставится флаг, как требует
        ТЗ: «старые записи не перезаписываются». Повторная отмена вернёт False.
        """
        async with self._db.conn.execute(
            """
            UPDATE operations SET is_cancelled = 1, cancelled_at = ?
            WHERE id = ? AND is_cancelled = 0
            """,
            (to_utc_text(now_utc()), operation_id),
        ) as cursor:
            changed = cursor.rowcount
        await self._db.conn.commit()
        return changed > 0

    async def has_start_balance(self) -> bool:
        """Стартовая сумма задаётся один раз: повторно — только через /correct."""
        async with self._db.conn.execute(
            "SELECT 1 FROM operations WHERE type = 'start' AND is_cancelled = 0 LIMIT 1"
        ) as cursor:
            return await cursor.fetchone() is not None

    async def set_start_balance(self, amount: int, created_by: int) -> int | None:
        """Записать стартовый баланс, если его ещё нет.

        Проверка и вставка идут одним запросом: иначе два быстрых /start
        могли бы создать две стартовые операции.
        """
        async with self._db.conn.execute(
            """
            INSERT INTO operations (
                type, amount, comment, source, created_by,
                occurred_at, created_at, local_date
            )
            SELECT 'start', ?, 'Стартовый баланс', 'manual', ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM operations WHERE type = 'start' AND is_cancelled = 0
            )
            RETURNING id
            """,
            (
                amount, created_by, to_utc_text(now_utc()),
                to_utc_text(now_utc()), local_date_of(now_utc(), self._tz),
            ),
        ) as cursor:
            row = await cursor.fetchone()
        await self._db.conn.commit()
        return int(row["id"]) if row else None

    # ---------- агрегаты ----------

    async def balance(self) -> int:
        """Текущий баланс = Σ amount по неотменённым операциям."""
        async with self._db.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM operations WHERE is_cancelled = 0"
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["total"])

    async def balance_before(self, local_date: str) -> int:
        """«Остаток на начало дня» — баланс на 00:00 указанного дня.

        В первый день это стартовая сумма: операций раньше просто нет.
        """
        async with self._db.conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total FROM operations
            WHERE is_cancelled = 0 AND local_date < ?
            """,
            (local_date,),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["total"])

    async def day_totals(self, local_date: str) -> dict[str, int]:
        """Поступления и расходы за день, по типам операций.

        Возвраты ApiPay (тип refund) уменьшают поступления за день, а не
        попадают в расходы: это отрицательная выручка, а не трата.
        """
        async with self._db.conn.execute(
            """
            SELECT type, COALESCE(SUM(amount), 0) AS total, COUNT(*) AS cnt
            FROM operations
            WHERE is_cancelled = 0 AND local_date = ?
            GROUP BY type
            """,
            (local_date,),
        ) as cursor:
            rows = await cursor.fetchall()

        totals = {row["type"]: int(row["total"]) for row in rows}
        counts = {row["type"]: int(row["cnt"]) for row in rows}
        return {
            "income": totals.get("income", 0) + totals.get("refund", 0),
            "income_count": counts.get("income", 0),
            "refund_count": counts.get("refund", 0),
            "expense": totals.get("expense", 0),
            "correction": totals.get("correction", 0),
            "start": totals.get("start", 0),
        }

    async def day_expenses_by_category(self, local_date: str) -> list[tuple[str, int]]:
        """Разбивка расходов дня по статьям — строки «• Закуп — 80 000 ₸»."""
        async with self._db.conn.execute(
            """
            SELECT COALESCE(NULLIF(category, ''), 'Прочее') AS name,
                   SUM(amount) AS total
            FROM operations
            WHERE is_cancelled = 0 AND local_date = ? AND type = 'expense'
            GROUP BY name
            ORDER BY total ASC
            """,
            (local_date,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [(row["name"], int(row["total"])) for row in rows]

    async def recent_operations(self, limit: int = 10) -> list[Operation]:
        """Последние операции для кнопки «История».

        Отменённые показываем тоже — пользователю важно видеть, что отмена
        случилась, иначе операция просто исчезает без следа.
        """
        async with self._db.conn.execute(
            "SELECT * FROM operations ORDER BY occurred_at DESC, id DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Operation.from_row(row) for row in rows]

    async def count_apipay_operations(self, local_date: str) -> int:
        async with self._db.conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM operations
            WHERE is_cancelled = 0 AND local_date = ? AND source = 'apipay'
            """,
            (local_date,),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["cnt"])
