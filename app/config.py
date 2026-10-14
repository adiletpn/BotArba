"""Конфигурация приложения.

Все секреты читаются из переменных окружения (требование ТЗ): в коде их нет.
Локально переменные берутся из .env, на Railway — из переменных сервиса.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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
    if value < 0:
        raise ConfigError(f"{name} не может быть отрицательным")
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


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    owner_ids: tuple[int, ...]

    apipay_api_key: str
    apipay_webhook_secret: str
    apipay_base_url: str
    apipay_sandbox: bool
    apipay_webhook_path: str

    db_path: Path
    timezone: ZoneInfo
    timezone_name: str
    summary_hour: int
    summary_minute: int

    web_host: str
    web_port: int

    sync_window_days: int
    undo_window_minutes: int

    backup_dir: Path
    backup_keep_days: int

    sheets_webapp_url: str
    sheets_token: str
    sheets_sync_minutes: int

    @property
    def webhook_route(self) -> str:
        return f"/webhook/{self.apipay_webhook_path}"

    @property
    def sheets_enabled(self) -> bool:
        """Без URL и токена выгрузка молча отключена — бот работает как обычно."""
        return bool(self.sheets_webapp_url and self.sheets_token)

    @property
    def apipay_enabled(self) -> bool:
        """Без ключа бот работает как чисто ручной учёт: /income, /correct, расходы."""
        return bool(self.apipay_api_key)


def load_settings(env_file: str | os.PathLike[str] | None = ".env") -> Settings:
    """Собрать настройки из окружения.

    .env не перезаписывает уже выставленные переменные: на Railway переменные
    сервиса должны побеждать случайно закоммиченный файл.
    """
    if env_file and Path(env_file).exists():
        load_dotenv(env_file, override=False)

    timezone_name = _optional("TIMEZONE", "Asia/Almaty") or "Asia/Almaty"
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Неизвестный часовой пояс TIMEZONE={timezone_name!r}") from exc

    summary_hour, summary_minute = _summary_time(_optional("SUMMARY_TIME", "21:00") or "21:00")

    return Settings(
        bot_token=_require("BOT_TOKEN"),
        owner_ids=_owner_ids(_require("OWNER_TELEGRAM_IDS")),
        apipay_api_key=_optional("APIPAY_API_KEY"),
        apipay_webhook_secret=_optional("APIPAY_WEBHOOK_SECRET"),
        apipay_base_url=(_optional("APIPAY_BASE_URL", "https://api.apipay.kz/api/v1")
                         or "https://api.apipay.kz/api/v1").rstrip("/"),
        apipay_sandbox=_flag("APIPAY_SANDBOX", False),
        apipay_webhook_path=_optional("APIPAY_WEBHOOK_PATH", "apipay") or "apipay",
        db_path=Path(_optional("DB_PATH", "./data/botarba.db") or "./data/botarba.db"),
        timezone=timezone,
        timezone_name=timezone_name,
        summary_hour=summary_hour,
        summary_minute=summary_minute,
        web_host=_optional("WEB_HOST", "0.0.0.0") or "0.0.0.0",
        # Railway задаёт порт сам через PORT и ждёт, что процесс слушает именно его.
        # WEB_PORT остаётся для локального запуска и VPS.
        web_port=_positive_int("PORT", 0) or _positive_int("WEB_PORT", 8080),
        sync_window_days=_positive_int("SYNC_WINDOW_DAYS", 2),
        undo_window_minutes=_positive_int("UNDO_WINDOW_MINUTES", 10),
        backup_dir=Path(_optional("BACKUP_DIR", "./backups") or "./backups"),
        backup_keep_days=_positive_int("BACKUP_KEEP_DAYS", 14),
        sheets_webapp_url=_optional("SHEETS_WEBAPP_URL"),
        sheets_token=_optional("SHEETS_TOKEN"),
        sheets_sync_minutes=_positive_int("SHEETS_SYNC_MINUTES", 10),
    )
