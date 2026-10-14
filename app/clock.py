"""Время и календарные сутки мерчанта.

Внутри храним UTC, пользователю показываем Asia/Almaty. Сутки считаем
по зоне мерчанта: «сводка за 13.10.2026» — это 00:00–23:59:59 в Алматы,
а не в UTC, иначе вечерние оплаты уехали бы в следующий день.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_text(moment: datetime) -> str:
    """Сериализовать момент для SQLite: ISO 8601 в UTC.

    Наивный datetime считаем уже UTC — так дешевле, чем падать на каждом
    вызове, а наивные значения в коде возникают только из самого SQLite.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def parse_utc_text(raw: str) -> datetime:
    """Разобрать момент из SQLite или из JSON ApiPay (ISO 8601)."""
    text = raw.strip().replace("Z", "+00:00")
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def local_date_of(moment: datetime, tz: ZoneInfo) -> str:
    """Календарный день момента в зоне мерчанта: 'YYYY-MM-DD'."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).date().isoformat()


def today_local(tz: ZoneInfo) -> str:
    return local_date_of(now_utc(), tz)


def format_date_ru(local_date: str) -> str:
    """'2026-10-13' -> '13.10.2026' (формат из образцов ТЗ)."""
    return date.fromisoformat(local_date).strftime("%d.%m.%Y")


def format_time_local(moment: datetime, tz: ZoneInfo) -> str:
    """'18:40' — для пометки «Данные ApiPay обновлены в 18:40»."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).strftime("%H:%M")


def shift_local_date(local_date: str, days: int) -> str:
    return (date.fromisoformat(local_date) + timedelta(days=days)).isoformat()
