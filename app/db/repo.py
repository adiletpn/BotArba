"""Запросы к базе.

Все суммы — тиыны со знаком. Баланс нигде не кэшируется: каждая цифра
в интерфейсе — это агрегат по таблице operations, как требует ТЗ.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from collections.abc import Callable

from app.clock import local_date_of, now_utc, to_utc_text
from app.db.database import Database
from app.db.models import Operation, OperationSource, OperationType

logger = logging.getLogger(__name__)


class Repo:
    def __init__(self, db: Database, tz: ZoneInfo) -> None:
        self._db = db
        self._tz = tz
        self._on_change: Callable[[], None] | None = None

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    def set_change_listener(self, listener: Callable[[], None] | None) -> None:
        """Подписаться на «данные изменились».

        Нужно выгрузке в Google Таблицы. Репозиторий при этом о таблицах
        ничего не знает — он просто дёргает колбэк, поэтому слой доступа к
        базе не зависит от интеграций.
        """
        self._on_change = listener

    def _changed(self) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change()
        except Exception:
            # Сломанный слушатель не должен ронять запись операции.
            logger.exception("Слушатель изменений упал")

    # ---------- users / белый список ----------

    async def ensure_owners(self, owner_ids: tuple[int, ...]) -> None:
        """Синхронизировать белый список из .env в таблицу users.

        .env — источник истины для доступа, причём в ОБЕ стороны: кого нет в
        переменной, тот доступ теряет. Иначе смена владельца не отзывала бы
        доступ у прежнего, и вечерняя сводка продолжала бы уходить ему.

        Строки не удаляются: на users ссылается operations.created_by, и
        удаление снесло бы историю операций по внешнему ключу. Вместо этого
        снимается is_active — имя и дата появления сохраняются.
        """
        now = to_utc_text(now_utc())
        for telegram_id in owner_ids:
            await self._db.conn.execute(
                """
                INSERT INTO users (telegram_id, name, role, created_at, is_active)
                VALUES (?, '', 'owner', ?, 1)
                ON CONFLICT (telegram_id)
                    DO UPDATE SET role = 'owner', is_active = 1
                """,
                (telegram_id, now),
            )

        placeholders = ",".join("?" * len(owner_ids))
        revoked = await self._db.conn.execute(
            f"""
            UPDATE users SET is_active = 0
            WHERE is_active = 1 AND telegram_id NOT IN ({placeholders})
            """,
            owner_ids,
        )
        if revoked.rowcount:
            logger.info("Доступ отозван у %s пользователей", revoked.rowcount)
        await self._db.conn.commit()

    async def is_allowed(self, telegram_id: int) -> bool:
        async with self._db.conn.execute(
            "SELECT 1 FROM users WHERE telegram_id = ? AND is_active = 1",
            (telegram_id,),
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
            "SELECT telegram_id FROM users WHERE is_active = 1 ORDER BY telegram_id"
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

        self._changed()
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

        if changed:
            self._changed()
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

        if row is not None:
            self._changed()
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
        """Баланс строго до начала указанного дня."""
        async with self._db.conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total FROM operations
            WHERE is_cancelled = 0 AND local_date < ?
            """,
            (local_date,),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["total"])

    async def opening_balance(self, local_date: str) -> int:
        """«Остаток на начало дня» для сводки.

        Это баланс до начала дня ПЛЮС стартовая сумма, если её задали в этот
        же день. ТЗ прямо требует: «в первый день это стартовая сумма» — иначе
        в день установки бота сводка показывала бы «На начало дня: 0 ₸» при
        непустом балансе, и строки не сходились бы друг с другом.

        Стартовая сумма — не выручка дня, а точка отсчёта, поэтому в
        «Поступления» она тоже не идёт.
        """
        async with self._db.conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total FROM operations
            WHERE is_cancelled = 0
              AND (local_date < ? OR (local_date = ? AND type = 'start'))
            """,
            (local_date, local_date),
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

    async def all_operations(self, limit: int = 20_000) -> list[Operation]:
        """Все операции по возрастанию — для выгрузки в таблицу.

        Выгрузка перезаписывает лист целиком, поэтому порядок должен быть
        стабильным и от старых к новым. Лимит — страховка от того, что за
        годы таблица перестанет влезать в один запрос.
        """
        async with self._db.conn.execute(
            """
            SELECT * FROM operations
            ORDER BY occurred_at ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Operation.from_row(row) for row in rows]

    async def daily_rows(self) -> list[dict[str, int | str]]:
        """Сводка по дням: поступления, расходы, корректировки за каждый день.

        Отменённые операции исключены, возвраты сложены с поступлениями —
        та же логика, что в дневной сводке бота, чтобы цифры в таблице и в
        Telegram не расходились.
        """
        async with self._db.conn.execute(
            """
            SELECT
                local_date,
                COALESCE(SUM(CASE WHEN type IN ('income', 'refund')
                                  THEN amount END), 0) AS income,
                COALESCE(SUM(CASE WHEN type = 'expense' THEN amount END), 0) AS expense,
                COALESCE(SUM(CASE WHEN type = 'correction' THEN amount END), 0) AS correction,
                COALESCE(SUM(CASE WHEN type = 'start' THEN amount END), 0) AS start,
                COUNT(CASE WHEN type = 'income' THEN 1 END) AS payments
            FROM operations
            WHERE is_cancelled = 0
            GROUP BY local_date
            ORDER BY local_date ASC
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

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

    # ---------- категории ----------

    #: Статьи расходов из ТЗ. Порядок — порядок кнопок.
    DEFAULT_CATEGORIES = ("Закуп", "Аренда", "Зарплата", "Реклама", "Налоги", "Прочее")

    async def seed_categories(self) -> None:
        for sort, name in enumerate(self.DEFAULT_CATEGORIES, start=1):
            await self._db.conn.execute(
                """
                INSERT INTO categories (name, is_active, sort) VALUES (?, 1, ?)
                ON CONFLICT (name) DO NOTHING
                """,
                (name, sort),
            )
        await self._db.conn.commit()

    async def active_categories(self) -> list[str]:
        async with self._db.conn.execute(
            "SELECT name FROM categories WHERE is_active = 1 ORDER BY sort, name"
        ) as cursor:
            return [row["name"] for row in await cursor.fetchall()]

    async def add_category(self, name: str) -> None:
        """Запомнить статью, введённую текстом, чтобы она появилась в кнопках."""
        cleaned = name.strip()
        if not cleaned:
            return
        await self._db.conn.execute(
            """
            INSERT INTO categories (name, is_active, sort) VALUES (?, 1, 500)
            ON CONFLICT (name) DO UPDATE SET is_active = 1
            """,
            (cleaned,),
        )
        await self._db.conn.commit()

    # ---------- настройки ----------

    async def get_setting(self, key: str) -> str | None:
        async with self._db.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self._db.conn.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
            """,
            (key, value, to_utc_text(now_utc())),
        )
        await self._db.conn.commit()

    SUMMARY_TIME_KEY = "summary_time"
    TIMEZONE_KEY = "timezone"
    LAST_SYNC_KEY = "last_apipay_sync"

    async def seed_settings(self, summary_time: str, timezone_name: str) -> None:
        """Записать настройки при первом запуске.

        .env задаёт только НАЧАЛЬНОЕ значение. Дальше источник истины — база:
        ТЗ требует, чтобы время сводки менялось в настройках, а не редеплоем.
        """
        if await self.get_setting(self.SUMMARY_TIME_KEY) is None:
            await self.set_setting(self.SUMMARY_TIME_KEY, summary_time)
        # Зона в базе — справочная: расписания строит APScheduler по TIMEZONE
        # из окружения, потому что сменить её на лету нельзя без пересборки
        # всех триггеров.
        await self.set_setting(self.TIMEZONE_KEY, timezone_name)

    async def get_summary_time(self, default: tuple[int, int]) -> tuple[int, int]:
        """Время вечерней сводки из настроек, иначе значение по умолчанию."""
        raw = await self.get_setting(self.SUMMARY_TIME_KEY)
        if not raw:
            return default
        try:
            hour_str, minute_str = raw.split(":", 1)
            hour, minute = int(hour_str), int(minute_str)
        except ValueError:
            logger.warning("Некорректное %s в настройках: %r", self.SUMMARY_TIME_KEY, raw)
            return default
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            logger.warning("%s вне диапазона: %r", self.SUMMARY_TIME_KEY, raw)
            return default
        return hour, minute

    async def set_summary_time(self, hour: int, minute: int) -> None:
        await self.set_setting(self.SUMMARY_TIME_KEY, f"{hour:02d}:{minute:02d}")

    async def get_last_apipay_sync(self) -> datetime | None:
        """Когда последний раз успешно сверились с ApiPay.

        Нужно для пометки «Данные ApiPay обновлены в 18:40», которую ТЗ требует
        показывать, если ApiPay недоступен в момент формирования сводки.
        """
        raw = await self.get_setting(self.LAST_SYNC_KEY)
        if not raw:
            return None
        from app.clock import parse_utc_text

        return parse_utc_text(raw)

    async def mark_apipay_sync(self, moment: datetime | None = None) -> None:
        await self.set_setting(self.LAST_SYNC_KEY, to_utc_text(moment or now_utc()))

    # ---------- журнал вебхуков ----------

    async def log_webhook(
        self,
        *,
        body: str,
        status_code: int,
        outcome: str,
        event: str | None = None,
        invoice_id: str | None = None,
        signature_ok: bool | None = None,
        is_sandbox: bool | None = None,
    ) -> None:
        """Записать входящий вебхук. ТЗ: логируем ВСЕ, включая отвергнутые.

        Тело режем до 8 КБ: спорный случай разбирается по полям события, а
        раздувать базу полным дампом корзины товаров смысла нет.
        """
        await self._db.conn.execute(
            """
            INSERT INTO webhook_logs (
                received_at, event, invoice_id, signature_ok,
                is_sandbox, status_code, outcome, body
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                to_utc_text(now_utc()), event, invoice_id,
                None if signature_ok is None else int(signature_ok),
                None if is_sandbox is None else int(is_sandbox),
                status_code, outcome, body[:8192],
            ),
        )
        await self._db.conn.commit()

    # ---------- возвраты по счёту ----------

    async def refunded_total_for_invoice(self, invoice_id: int) -> int:
        """Сколько уже записано возвратов по счёту (положительное число).

        Возвраты помечаются external_id вида "refund:<invoice_id>:<...>",
        поэтому сумма по счёту берётся префиксным поиском — он идёт по
        UNIQUE-индексу external_id.
        """
        async with self._db.conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total FROM operations
            WHERE is_cancelled = 0 AND type = 'refund'
              AND external_id LIKE ? || '%'
            """,
            (f"refund:{invoice_id}:",),
        ) as cursor:
            row = await cursor.fetchone()
        return -int(row["total"])
