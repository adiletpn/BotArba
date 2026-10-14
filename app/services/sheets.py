"""Выгрузка в Google Таблицы.

Схема простая: бот отправляет в веб-приложение Apps Script ПОЛНЫЙ снимок
операций, скрипт перезаписывает листы целиком.

Почему снимок, а не добавление строк. Операции меняются уже после записи:
расход отменяют кнопкой, возврат уменьшает поступление, продажа с кассы Kaspi
приходит задним числом и встаёт в середину уже выгруженного дня. С добавлением
строк всё это пришлось бы отслеживать и править точечно; полная перезапись
делает выгрузку идемпотентной — её можно повторять сколько угодно, и таблица
всегда равна базе.

База остаётся источником истины: если таблица недоступна, бот продолжает
работать и просто повторит выгрузку позже.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from app.clock import now_utc
from app.db.models import OPERATION_LABELS
from app.money import TIYN_PER_TENGE

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

OPERATIONS_HEADER = (
    "ID", "Дата", "Время", "Тип", "Сумма ₸", "Статья",
    "Комментарий", "Источник", "ID в ApiPay", "Отменена",
)

DAILY_HEADER = (
    "Дата", "Поступления ₸", "Расходы ₸", "Корректировки ₸",
    "Итог за день ₸", "Баланс на конец дня ₸", "Оплат",
)

SOURCE_LABELS = {"apipay": "Kaspi / ApiPay", "manual": "Вручную"}


def _tenge(tiyn: int) -> float:
    """Тиыны -> тенге числом, чтобы в таблице работали суммы и фильтры.

    Только для отображения: внутри бота и в базе суммы остаются целыми
    тиынами, так что округление здесь ни на что не влияет.
    """
    return tiyn / TIYN_PER_TENGE


async def build_snapshot(repo, tz) -> dict:
    """Собрать снимок базы в виде, готовом для записи в листы."""
    operations = await repo.all_operations()

    operation_rows = []
    for operation in operations:
        local = operation.occurred_at.astimezone(tz)
        operation_rows.append([
            operation.id,
            local.strftime("%d.%m.%Y"),
            local.strftime("%H:%M"),
            OPERATION_LABELS.get(operation.type, operation.type),
            _tenge(operation.amount),
            operation.category or "",
            operation.comment or "",
            SOURCE_LABELS.get(operation.source, operation.source),
            operation.external_id or "",
            "да" if operation.is_cancelled else "",
        ])

    # Баланс на конец дня — накопительный итог, его в SQL считать дороже,
    # чем пройти по уже отсортированным дням здесь.
    daily_rows = []
    running = 0
    for row in await repo.daily_rows():
        day_total = (
            int(row["income"]) + int(row["expense"])
            + int(row["correction"]) + int(row["start"])
        )
        running += day_total
        daily_rows.append([
            row["local_date"],
            _tenge(int(row["income"])),
            _tenge(int(row["expense"])),
            _tenge(int(row["correction"])),
            _tenge(day_total),
            _tenge(running),
            int(row["payments"]),
        ])

    return {
        "operations": {"header": list(OPERATIONS_HEADER), "rows": operation_rows},
        "daily": {"header": list(DAILY_HEADER), "rows": daily_rows},
        "generated_at": now_utc().astimezone(tz).strftime("%d.%m.%Y %H:%M"),
    }


async def push_snapshot(settings, snapshot: dict) -> bool:
    """Отправить снимок в веб-приложение Apps Script.

    Токен идёт в теле, а не в URL: адрес веб-приложения попадает в логи
    и историю редиректов, тело запроса — нет.
    """
    payload = {"token": settings.sheets_token, **snapshot}
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            # Apps Script отвечает редиректом на googleusercontent.com,
            # поэтому редиректы обязаны разрешаться (так и по умолчанию).
            async with session.post(settings.sheets_webapp_url, json=payload) as response:
                body = (await response.text())[:300]
                if response.status != 200:
                    logger.warning("Google Таблицы: HTTP %s — %s", response.status, body)
                    return False
                if '"ok"' not in body and "ok" not in body:
                    logger.warning("Google Таблицы ответили неожиданно: %s", body)
                    return False
                return True
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.warning("Google Таблицы недоступны: %s", exc)
        return False


async def sync(repo, settings) -> bool:
    """Выгрузить базу в таблицу. Вернуть True при успехе."""
    if not settings.sheets_enabled:
        return False

    snapshot = await build_snapshot(repo, settings.timezone)
    ok = await push_snapshot(settings, snapshot)
    if ok:
        logger.info(
            "Google Таблицы обновлены: операций %s, дней %s",
            len(snapshot["operations"]["rows"]), len(snapshot["daily"]["rows"]),
        )
    return ok


class SheetsSyncer:
    """Фоновая выгрузка по флагу «есть изменения».

    Зачем не выгружать прямо из хендлера: отправка в Google может занять
    секунды или повиснуть в таймаут, а пользователь в это время ждёт ответа
    на «Расход». Поэтому хендлеры только поднимают флаг, а выгружает отдельная
    задача — не чаще, чем раз в `min_interval` секунд, сколько бы операций
    ни внесли подряд.
    """

    def __init__(self, repo, settings, min_interval: float = 15.0) -> None:
        self._repo = repo
        self._settings = settings
        self._min_interval = min_interval
        self._dirty = asyncio.Event()
        self._task: asyncio.Task | None = None

    def request(self) -> None:
        """Отметить, что база изменилась. Безопасно вызывать сколько угодно."""
        if self._settings.sheets_enabled:
            self._dirty.set()

    def start(self) -> None:
        if self._settings.sheets_enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="sheets-sync")
            logger.info("Выгрузка в Google Таблицы включена")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            try:
                await sync(self._repo, self._settings)
            except Exception:
                # Упавшая выгрузка не должна убивать задачу: следующая
                # операция снова поднимет флаг, и мы попробуем ещё раз.
                logger.exception("Выгрузка в Google Таблицы сорвалась")
            # Пауза ПОСЛЕ выгрузки: серия быстрых правок склеится в один запрос.
            await asyncio.sleep(self._min_interval)
