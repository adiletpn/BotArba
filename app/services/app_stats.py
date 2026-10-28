"""Статистика приложения ArbaFood: пользователи, активность, заказы.

Источники:
* Firebase Auth — дата регистрации и время последней активности. Последняя
  активность обновляется, когда человек открывает приложение (обновление
  токена), поэтому это честнее любого поля в базе, которое пишет само
  приложение.
* Firestore, коллекция ``orders`` — заказы с ``placedAt`` и ``status``.

firebase-admin синхронный, поэтому подсчёт выполняется в отдельном потоке:
бот не должен замирать на 3 секунды, пока идёт выборка.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

#: Кого считать активным: открывал приложение за столько дней.
ACTIVE_WINDOW_DAYS = 7

_APP_NAME = "arbafood-stats"

#: Последняя ошибка статистики — для /health. Только текст исключения,
#: без содержимого ключа: его тут не бывает.
last_error: str | None = None


def _remember(exc: Exception) -> None:
    global last_error
    last_error = f"{type(exc).__name__}: {exc}"[:300]


@dataclass(frozen=True, slots=True)
class AppStats:
    day: str                  # YYYY-MM-DD, за какой день считались заказы и регистрации
    is_today: bool
    computed_at: datetime     # в зоне мерчанта
    users_total: int
    users_active: int
    buyers: int               # разных людей с неотменённым заказом за день
    orders: int               # всех заказов за день
    orders_cancelled: int
    new_users: int


class StatsError(RuntimeError):
    """Firebase не ответил или ключ неверный."""


def _firebase_app(credentials_json: str):
    """Инициализировать firebase-admin один раз на процесс."""
    import firebase_admin
    from firebase_admin import credentials

    try:
        return firebase_admin.get_app(_APP_NAME)
    except ValueError:
        pass
    info = parse_credentials(credentials_json)
    return firebase_admin.initialize_app(
        credentials.Certificate(info), name=_APP_NAME
    )


def parse_credentials(raw: str) -> dict:
    """Ключ сервисного аккаунта из переменной окружения: JSON или base64.

    base64 — основной способ для Railway: одна строка без кавычек, запятых и
    переносов. JSON с переносами строк при вставке в переменную портился
    (переносы превращались в запятые), и ключ переставал читаться.
    """
    import base64

    text = (raw or "").strip()
    if not text:
        raise StatsError("ключ Firebase пуст")
    if text.startswith("{"):
        try:
            return json.loads(text)
        except ValueError as exc:
            raise StatsError(
                "ключ Firebase — испорченный JSON; вставьте его в base64"
            ) from exc
    try:
        return json.loads(base64.b64decode(text, validate=True).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise StatsError("ключ Firebase не похож ни на JSON, ни на base64") from exc


def _day_bounds(local_day: str, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(date.fromisoformat(local_day), time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def _collect(credentials_json: str, local_day: str, tz: ZoneInfo) -> AppStats:
    from firebase_admin import auth, firestore
    from google.cloud.firestore_v1.base_query import FieldFilter

    app = _firebase_app(credentials_json)
    now = datetime.now(tz)
    start, end = _day_bounds(local_day, tz)

    def ms(moment: datetime) -> int:
        return int(moment.timestamp() * 1000)

    active_since = ms(now - timedelta(days=ACTIVE_WINDOW_DAYS))
    day_from, day_to = ms(start), ms(end)

    users_total = users_active = new_users = 0
    page = auth.list_users(app=app)
    while page:
        for user in page.users:
            meta = user.user_metadata
            users_total += 1
            last_seen = max(
                filter(None, (meta.last_refresh_timestamp, meta.last_sign_in_timestamp)),
                default=0,
            )
            if last_seen >= active_since:
                users_active += 1
            if day_from <= (meta.creation_timestamp or 0) < day_to:
                new_users += 1
        page = page.get_next_page()

    orders = [
        snapshot.to_dict() or {}
        for snapshot in firestore.client(app=app)
        .collection("orders")
        .where(filter=FieldFilter("placedAt", ">=", start))
        .where(filter=FieldFilter("placedAt", "<", end))
        .select(["status", "userId"])
        .stream()
    ]
    cancelled = sum(1 for order in orders if order.get("status") == "cancelled")
    buyers = {
        order.get("userId")
        for order in orders
        if order.get("status") != "cancelled" and order.get("userId")
    }

    return AppStats(
        day=local_day,
        is_today=local_day == now.date().isoformat(),
        computed_at=now,
        users_total=users_total,
        users_active=users_active,
        buyers=len(buyers),
        orders=len(orders),
        orders_cancelled=cancelled,
        new_users=new_users,
    )


async def collect_stats(credentials_json: str, local_day: str, tz: ZoneInfo) -> AppStats:
    global last_error
    try:
        result = await asyncio.to_thread(_collect, credentials_json, local_day, tz)
        last_error = None
        return result
    except StatsError as exc:
        _remember(exc)
        raise
    except Exception as exc:
        _remember(exc)
        logger.exception("Статистика ArbaFood не собралась")
        raise StatsError(str(exc)) from exc


def percent(part: int, whole: int) -> str:
    """«38%», а для малых долей — с десятыми: «0.2%», иначе всё было бы «0%»."""
    if whole <= 0:
        return "—"
    value = part * 100 / whole
    if 0 < value < 1:
        return f"{value:.1f}%"
    return f"{round(value)}%"


def _num(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def render_stats(stats: AppStats) -> str:
    """Текст сводки. Без HTML-обёртки — её добавляет отправитель."""
    from app.clock import format_date_ru

    if stats.is_today:
        title = f"📈 ArbaFood — сегодня, {stats.computed_at:%d.%m %H:%M}"
        day_word = "сегодня"
    else:
        title = f"📈 ArbaFood — итоги за {format_date_ru(stats.day)}"
        day_word = "за день"

    def row(label: str, value: str, note: str = "") -> str:
        line = f"{label:<22}{value:>7}"
        return f"{line}  {note}" if note else line

    lines = [
        title,
        "",
        row("Пользователей:", _num(stats.users_total)),
        row(f"Активных за {ACTIVE_WINDOW_DAYS} дн.:", _num(stats.users_active),
            f"({percent(stats.users_active, stats.users_total)})"),
        row(f"Заказали {day_word}:", _num(stats.buyers),
            f"({percent(stats.buyers, stats.users_active)} активных)"),
        row(f"Новых {day_word}:", _num(stats.new_users)),
        "",
        row("Заказов:", _num(stats.orders),
            f"отменено {stats.orders_cancelled}" if stats.orders_cancelled else ""),
    ]
    return "\n".join(lines)


def _collect_history(credentials_json: str, days: list[str], tz: ZoneInfo) -> list[dict]:
    """Восстановимые цифры за прошлые дни — без «активных».

    Один проход по пользователям и один запрос заказов на весь период:
    30 отдельных подсчётов заняли бы полторы минуты.
    """
    from firebase_admin import auth, firestore
    from google.cloud.firestore_v1.base_query import FieldFilter

    app = _firebase_app(credentials_json)
    bounds = {day: _day_bounds(day, tz) for day in days}
    period_start = min(start for start, _ in bounds.values())

    created: list[int] = []
    page = auth.list_users(app=app)
    while page:
        created.extend(u.user_metadata.creation_timestamp or 0 for u in page.users)
        page = page.get_next_page()

    per_day = {day: {"orders": 0, "cancelled": 0, "buyers": set()} for day in days}
    for snapshot in (
        firestore.client(app=app).collection("orders")
        .where(filter=FieldFilter("placedAt", ">=", period_start))
        .select(["placedAt", "status", "userId"]).stream()
    ):
        order = snapshot.to_dict() or {}
        placed = order.get("placedAt")
        if not placed:
            continue
        bucket = per_day.get(placed.astimezone(tz).date().isoformat())
        if bucket is None:
            continue
        bucket["orders"] += 1
        if order.get("status") == "cancelled":
            bucket["cancelled"] += 1
        elif order.get("userId"):
            bucket["buyers"].add(order["userId"])

    rows = []
    for day, (start, end) in bounds.items():
        start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
        rows.append({
            "day": day,
            # «Всего пользователей» на конец того дня — по датам регистрации.
            "users_total": sum(1 for c in created if c < end_ms),
            "users_active": None,
            "buyers": len(per_day[day]["buyers"]),
            "orders": per_day[day]["orders"],
            "orders_cancelled": per_day[day]["cancelled"],
            "new_users": sum(1 for c in created if start_ms <= c < end_ms),
        })
    return rows


async def collect_history(credentials_json: str, days: list[str], tz: ZoneInfo) -> list[dict]:
    try:
        return await asyncio.to_thread(_collect_history, credentials_json, days, tz)
    except StatsError as exc:
        _remember(exc)
        raise
    except Exception as exc:
        _remember(exc)
        logger.exception("История статистики ArbaFood не собралась")
        raise StatsError(str(exc)) from exc


async def capture_stats(repo, settings, local_day: str) -> AppStats:
    """Посчитать статистику за день и сохранить снимок в базу."""
    stats = await collect_stats(settings.firebase_credentials, local_day, settings.timezone)
    await repo.save_app_stats(
        day=stats.day, users_total=stats.users_total, users_active=stats.users_active,
        buyers=stats.buyers, orders=stats.orders, orders_cancelled=stats.orders_cancelled,
        new_users=stats.new_users,
    )
    return stats


#: Сколько дней истории восстановить при первом запуске.
BACKFILL_DAYS = 30


async def backfill_history(repo, settings) -> int:
    """Заполнить прошлые дни, если снимков ещё нет. Вернуть, сколько дней записано."""
    from app.clock import shift_local_date, today_local

    if await repo.has_app_stats():
        return 0
    today = today_local(settings.timezone)
    days = [shift_local_date(today, -i) for i in range(BACKFILL_DAYS, 0, -1)]
    rows = await collect_history(settings.firebase_credentials, days, settings.timezone)
    for row in rows:
        await repo.save_app_stats(**row, keep_active=True)
    logger.info("Статистика ArbaFood: восстановлено %s дней истории", len(rows))
    return len(rows)
