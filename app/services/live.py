"""Живой режим: деньги видны в Telegram сразу, а не только вечерней сводкой.

Два независимых переключателя на каждого владельца (команда /live):

* **Табло** — одно закреплённое сообщение, которое бот переписывает при
  каждой операции: выручка и расходы за сегодня, баланс, последние движения.
  Чат не засоряется, а актуальная картина всегда сверху.
* **Уведомления** — отдельное сообщение на каждое поступление и расход.
  При 70–130 оплатах в день это шумно, поэтому включается отдельно.

Как и выгрузка в Google Таблицы, работа идёт в фоновой задаче по флагу
«есть изменения»: запись операции не ждёт ответа Telegram, а серия оплат,
пришедшая одной сверкой, склеивается в одно обновление табло.

Какие операции уже разосланы, помним по id последней (``live_watermark``),
а не по времени: продажа из истории Kaspi приходит задним числом.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.clock import format_date_ru, local_date_of, now_utc
from app.db.models import Operation
from app.money import format_delta, format_tenge

logger = logging.getLogger(__name__)

BOARD_KEY = "live_board:{}"        # id закреплённого сообщения-табло
NOTIFY_KEY = "live_notify:{}"      # "1" — слать уведомления о каждой операции
WATERMARK_KEY = "live_watermark"   # id последней разосланной операции

#: Сколько последних движений показывать на табло.
BOARD_RECENT = 8

#: Если за один раз пришло больше операций, они уходят одним сообщением:
#: например, после простоя сверка подтянет сразу пачку оплат.
NOTIFY_BATCH_LIMIT = 5

#: Раз в столько секунд табло перерисовывается и без операций, чтобы после
#: полуночи оно показало новый день, а не застряло на вчерашнем.
IDLE_REFRESH_SECONDS = 300


def describe(operation: Operation) -> str:
    """Подпись операции: откуда деньги или на что ушли."""
    detail = operation.category or operation.comment or ""
    if operation.source == "apipay" and not detail:
        return "Kaspi" if operation.type == "income" else "Возврат Kaspi"
    if operation.type == "correction":
        return f"Корректировка{' — ' + detail if detail else ''}"
    if operation.type == "income" and not detail:
        return "Поступление"
    return detail or "Расход"


async def render_board(repo, tz, now: datetime | None = None) -> str:
    """Текст табло. Без HTML: оборачивает в <pre> отправитель."""
    moment = now or now_utc()
    today = local_date_of(moment, tz)
    totals = await repo.day_totals(today)
    balance = await repo.balance()

    lines = [f"🟢 LIVE · {format_date_ru(today)}", ""]
    income = format_delta(totals["income"])
    if totals["income_count"]:
        income += f"  ({totals['income_count']})"
    lines.append(f"{'Поступления:':<14}{income}")
    lines.append(f"{'Расходы:':<14}{format_delta(totals['expense'])}")
    if totals["correction"]:
        lines.append(f"{'Корректировки:':<14}{format_delta(totals['correction'])}")
    lines.append(f"{'Баланс:':<14}{format_tenge(balance)}")

    recent = [
        op for op in await repo.recent_operations(BOARD_RECENT * 2)
        if not op.is_cancelled and op.type != "start"
    ][:BOARD_RECENT]
    if recent:
        lines += ["", "Последние:"]
        for op in recent:
            when = op.occurred_at.astimezone(tz)
            stamp = when.strftime("%H:%M") if local_date_of(op.occurred_at, tz) == today \
                else when.strftime("%d.%m")
            lines.append(f"{stamp}  {format_delta(op.amount):>13}  {describe(op)}")

    last = recent[0].occurred_at.astimezone(tz).strftime("%H:%M") if recent else "—"
    lines += ["", f"Обновляется само · последняя операция в {last}"]
    return "\n".join(lines)


def render_notification(operations: list[Operation], balance: int, tz, names: dict[int, str]) -> str:
    """Текст уведомления об одной или нескольких новых операциях."""
    rows = []
    for op in operations:
        icon = "💰" if op.amount > 0 else "💸"
        row = f"{icon} {format_delta(op.amount)} · {describe(op)}"
        who = names.get(op.created_by or 0)
        if who:
            row += f" ({who})"
        rows.append(row)
    rows += ["", f"Баланс: {format_tenge(balance)}"]
    return "\n".join(rows)


class LiveBroadcaster:
    def __init__(self, bot, repo, settings, min_interval: float = 3.0) -> None:
        self._bot = bot
        self._repo = repo
        self._settings = settings
        self._min_interval = min_interval
        self._dirty = asyncio.Event()
        self._task: asyncio.Task | None = None
        # Что сейчас на табло у каждого — чтобы не дёргать Telegram зря.
        self._shown: dict[int, str] = {}

    def request(self) -> None:
        self._dirty.set()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="live-broadcast")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        # Первый проход сразу: табло догоняет базу после рестарта.
        self._dirty.set()
        while True:
            try:
                await asyncio.wait_for(self._dirty.wait(), timeout=IDLE_REFRESH_SECONDS)
            except asyncio.TimeoutError:
                pass
            self._dirty.clear()
            try:
                await self.tick()
            except Exception:
                logger.exception("Живой режим: обновление сорвалось")
            await asyncio.sleep(self._min_interval)

    async def tick(self) -> None:
        owners = await self._repo.owner_ids()
        await self._notify(owners)
        for telegram_id in owners:
            await self.refresh_board(telegram_id)

    # ---------- уведомления ----------

    async def _notify(self, owners: list[int]) -> None:
        raw = await self._repo.get_setting(WATERMARK_KEY)
        if raw is None:
            # Первый запуск: всё, что уже есть в базе, — история, а не новости.
            await self._repo.set_setting(WATERMARK_KEY, str(await self._repo.max_operation_id()))
            return

        fresh = await self._repo.operations_after(int(raw))
        if not fresh:
            return
        # Сначала двигаем отметку, потом шлём: упавшая отправка не должна
        # повторять ту же пачку каждые 3 секунды.
        await self._repo.set_setting(WATERMARK_KEY, str(fresh[-1].id))
        if len(fresh) >= 100:
            self._dirty.set()   # остаток пачки — следующим проходом

        news = [op for op in fresh if not op.is_cancelled and op.type != "start"]
        if not news:
            return
        subscribers = [
            tid for tid in owners
            if await self._repo.get_setting(NOTIFY_KEY.format(tid)) == "1"
        ]
        if not subscribers:
            return

        balance = await self._repo.balance()
        names = {}
        for op in news:
            if op.created_by and op.created_by not in names:
                names[op.created_by] = await self._repo.user_name(op.created_by)

        for telegram_id in subscribers:
            # Свою же операцию человеку пересказывать незачем — он её только что ввёл.
            mine = [op for op in news if op.created_by != telegram_id]
            if not mine:
                continue
            chunks = (
                [mine] if len(mine) > NOTIFY_BATCH_LIMIT else [[op] for op in mine]
            )
            for chunk in chunks:
                text = render_notification(chunk, balance, self._settings.timezone, names)
                try:
                    await self._bot.send_message(telegram_id, text)
                except Exception as exc:
                    logger.warning("Уведомление пользователю %s не ушло: %s", telegram_id, exc)
                    break

    # ---------- табло ----------

    async def refresh_board(self, telegram_id: int) -> None:
        raw = await self._repo.get_setting(BOARD_KEY.format(telegram_id))
        if not raw:
            return
        from app.bot.render import as_pre

        text = as_pre(await render_board(self._repo, self._settings.timezone))
        if self._shown.get(telegram_id) == text:
            return
        try:
            await self._bot.edit_message_text(
                text, chat_id=telegram_id, message_id=int(raw), parse_mode="HTML"
            )
        except Exception as exc:
            message = str(exc).lower()
            if "not modified" in message:
                pass
            elif "not found" in message or "can't be edited" in message or "forbidden" in message:
                # Табло удалили руками или бота заблокировали — выключаем,
                # иначе будем стучаться в пустоту каждую операцию.
                logger.info("Табло у %s пропало (%s), выключаю", telegram_id, exc)
                await self._repo.set_setting(BOARD_KEY.format(telegram_id), "")
                self._shown.pop(telegram_id, None)
                return
            else:
                logger.warning("Табло у %s не обновилось: %s", telegram_id, exc)
                return
        self._shown[telegram_id] = text

    async def enable_board(self, telegram_id: int) -> None:
        """Прислать табло и закрепить его."""
        from app.bot.render import as_pre

        text = as_pre(await render_board(self._repo, self._settings.timezone))
        sent = await self._bot.send_message(telegram_id, text, parse_mode="HTML")
        try:
            await self._bot.pin_chat_message(
                telegram_id, sent.message_id, disable_notification=True
            )
        except Exception as exc:
            logger.warning("Табло не закрепилось у %s: %s", telegram_id, exc)
        await self._repo.set_setting(BOARD_KEY.format(telegram_id), str(sent.message_id))
        self._shown[telegram_id] = text

    async def disable_board(self, telegram_id: int) -> None:
        raw = await self._repo.get_setting(BOARD_KEY.format(telegram_id))
        await self._repo.set_setting(BOARD_KEY.format(telegram_id), "")
        self._shown.pop(telegram_id, None)
        if raw:
            try:
                await self._bot.unpin_chat_message(telegram_id, message_id=int(raw))
            except Exception:
                pass

    async def board_enabled(self, telegram_id: int) -> bool:
        return bool(await self._repo.get_setting(BOARD_KEY.format(telegram_id)))

    async def notify_enabled(self, telegram_id: int) -> bool:
        return await self._repo.get_setting(NOTIFY_KEY.format(telegram_id)) == "1"

    async def set_notify(self, telegram_id: int, on: bool) -> None:
        await self._repo.set_setting(NOTIFY_KEY.format(telegram_id), "1" if on else "")
