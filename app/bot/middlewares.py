"""Middleware доступа.

ТЗ: «бот отвечает только пользователям из белого списка», и «посторонний
пользователь получает отказ» — отдельный критерий приёмки. Поэтому проверка
стоит в middleware, а не в хендлерах: новый хендлер не может случайно
оказаться открытым для всех.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from app.bot import texts

logger = logging.getLogger(__name__)


class WhitelistMiddleware(BaseMiddleware):
    def __init__(self, repo) -> None:
        self._repo = repo

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            # Служебные апдейты без пользователя (например, изменение чата)
            # до хендлеров не доходят, но и отказ им отправлять некуда.
            return None

        if not await self._repo.is_allowed(user.id):
            logger.warning(
                "Отказ в доступе: id=%s username=%s", user.id, user.username
            )
            await self._deny(event, user.id)
            return None

        if user.full_name:
            await self._repo.remember_name(user.id, user.full_name)

        data["user_id"] = user.id
        return await handler(event, data)

    @staticmethod
    async def _deny(event: TelegramObject, telegram_id: int) -> None:
        """Сказать «нет» — и ничего о владельце.

        В отказ включён Telegram ID самого обратившегося, и только он. Без
        этого свежую установку нельзя запустить: /whoami стоит за этой же
        проверкой, поэтому первый владелец не мог бы узнать свой id, чтобы
        вписать его в OWNER_TELEGRAM_IDS. Своё же id пользователь и так знает,
        так что это не утечка.
        """
        text = texts.ACCESS_DENIED.format(telegram_id=telegram_id)
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
