"""Конфигурация приложения.

Все секреты читаются из переменных окружения (требование ТЗ): в коде их нет.
Локально переменные берутся из .env, на Railway — из переменных сервиса.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Конфигурация неполная или некорректная — запускаться нельзя."""


def _require(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise ConfigError(f"Переменная окружения {name} не задана")
    return value


def _optional(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value.strip()


def _flag(name: str, default: bool = False) -> bool:
    raw = _optional(name).lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} должно быть true или false, получено {raw!r}")


def _positive_int(name: str, default: int) -> int:
    raw = _optional(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} должно быть целым числом, получено {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name} должно быть больше нуля")
    return value


def _owner_ids(raw: str) -> tuple[int, ...]:
    ids: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.append(int(chunk))
        except ValueError as exc:
            raise ConfigError(
                f"OWNER_TELEGRAM_IDS содержит не число: {chunk!r}"
            ) from exc
    if not ids:
        raise ConfigError(
            "OWNER_TELEGRAM_IDS пуст — боту некому отвечать. "
            "Укажите свой Telegram ID (команда /whoami подскажет его)."
        )
    return tuple(dict.fromkeys(ids))


def _summary_time(raw: str) -> tuple[int, int]:
    try:
        hour_str, minute_str = raw.split(":", 1)
        hour, minute = int(hour_str), int(minute_str)
    except ValueError as exc:
        raise ConfigError(f"SUMMARY_TIME должно быть в формате HH:MM, получено {raw!r}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ConfigError(f"SUMMARY_TIME вне диапазона: {raw!r}")
    return hour, minute
