"""Критерий приёмки: посторонний пользователь получает отказ."""

from aiogram.types import Chat, Message, User

from app.bot import texts
from app.bot.middlewares import WhitelistMiddleware
from tests.conftest import OWNER_ID

STRANGER_ID = 999_999


def _message(user_id: int, first_name: str = "Тест") -> Message:
    """Собрать Message без валидации Telegram API.

    model_construct нужен, потому что настоящий Message требует полей,
    которых у нас нет, а middleware смотрит только на event_from_user.
    Модели aiogram заморожены, поэтому имя задаётся здесь, а не присваиванием.
    """
    return Message.model_construct(
        message_id=1,
        date=None,
        chat=Chat.model_construct(id=user_id, type="private"),
        from_user=User.model_construct(
            id=user_id, is_bot=False, first_name=first_name, last_name=None
        ),
        text="/start",
    )


async def test_stranger_is_rejected_and_handler_never_runs(repo, monkeypatch):
    middleware = WhitelistMiddleware(repo)
    calls: list[str] = []
    replies: list[str] = []

    async def handler(event, data):
        calls.append("handler")

    event = _message(STRANGER_ID)
    monkeypatch.setattr(
        type(event), "answer",
        lambda self, text, *a, **kw: replies.append(text) or _noop(), raising=False,
    )

    await middleware(handler, event, {"event_from_user": event.from_user})

    assert calls == [], "хендлер не должен вызываться для постороннего"
    assert replies == [texts.ACCESS_DENIED]


async def _noop():
    return None


async def test_owner_passes_through(repo, monkeypatch):
    middleware = WhitelistMiddleware(repo)
    calls: list[int] = []

    async def handler(event, data):
        calls.append(data["user_id"])

    event = _message(OWNER_ID)
    await middleware(handler, event, {"event_from_user": event.from_user})

    assert calls == [OWNER_ID], "владелец из белого списка должен проходить"


async def test_middleware_remembers_the_display_name(repo):
    middleware = WhitelistMiddleware(repo)

    async def handler(event, data):
        return None

    event = _message(OWNER_ID, first_name="Адилет")
    await middleware(handler, event, {"event_from_user": event.from_user})

    async with repo._db.conn.execute(
        "SELECT name FROM users WHERE telegram_id = ?", (OWNER_ID,)
    ) as cursor:
        row = await cursor.fetchone()
    assert row["name"] == "Адилет"


async def test_updates_without_a_user_are_dropped(repo):
    middleware = WhitelistMiddleware(repo)
    calls: list[str] = []

    async def handler(event, data):
        calls.append("handler")

    await middleware(handler, _message(OWNER_ID), {})
    assert calls == []
