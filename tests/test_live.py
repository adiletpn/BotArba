"""Живой режим: табло и уведомления о каждой операции."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.live import (
    NOTIFY_BATCH_LIMIT,
    WATERMARK_KEY,
    LiveBroadcaster,
    render_board,
)
from tests.conftest import ALMATY, OWNER_ID

OTHER_ID = 2


def _plain(text: str) -> str:
    """Суммы печатаются с неразрывным пробелом — в проверках он мешает."""
    return text.replace("\xa0", " ")


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.edited: list[tuple[int, int, str]] = []
        self.pinned: list[tuple[int, int]] = []
        self.edit_error: Exception | None = None
        self._next_id = 100

    async def send_message(self, chat_id, text, **_):
        self.sent.append((chat_id, _plain(text)))
        self._next_id += 1
        return SimpleNamespace(message_id=self._next_id)

    async def edit_message_text(self, text, *, chat_id, message_id, **_):
        if self.edit_error:
            raise self.edit_error
        self.edited.append((chat_id, message_id, _plain(text)))

    async def pin_chat_message(self, chat_id, message_id, **_):
        self.pinned.append((chat_id, message_id))

    async def unpin_chat_message(self, chat_id, **_):
        pass


@pytest.fixture
async def two_owners(repo):
    await repo.ensure_owners((OWNER_ID, OTHER_ID))
    return repo


async def _sale(repo, invoice: int, tenge: int) -> int:
    return await repo.add_operation(
        type="income", amount=tenge * 100, source="apipay", external_id=f"invoice:{invoice}"
    )


async def test_board_shows_today_and_balance(repo):
    await repo.set_start_balance(1_000_000 * 100, created_by=OWNER_ID)
    await _sale(repo, 1, 190_000)
    await repo.add_operation(type="expense", amount=-100_000 * 100, category="Закуп",
                             created_by=OWNER_ID)

    text = _plain(await render_board(repo, ALMATY))

    assert "LIVE" in text
    assert "+190 000 ₸  (1)" in text
    assert "−100 000 ₸" in text
    assert "1 090 000 ₸" in text
    assert "Kaspi" in text and "Закуп" in text


async def test_first_run_does_not_replay_history(two_owners, settings):
    repo = two_owners
    await _sale(repo, 1, 5_000)
    bot = FakeBot()
    live = LiveBroadcaster(bot, repo, settings)
    await live.set_notify(OWNER_ID, True)

    await live.tick()

    assert bot.sent == []
    assert await repo.get_setting(WATERMARK_KEY) == str(await repo.max_operation_id())


async def test_each_new_operation_is_sent_once(two_owners, settings):
    repo = two_owners
    bot = FakeBot()
    live = LiveBroadcaster(bot, repo, settings)
    await live.set_notify(OWNER_ID, True)
    await live.tick()   # отметка на текущем конце

    await _sale(repo, 1, 4_500)
    await _sale(repo, 2, 2_300)
    await live.tick()
    await live.tick()   # повторный проход ничего не шлёт

    texts = [text for chat, text in bot.sent if chat == OWNER_ID]
    assert len(texts) == 2
    assert "💰 +4 500 ₸ · Kaspi" in texts[0]
    assert "Баланс: 6 800 ₸" in texts[1]


async def test_own_expense_is_not_echoed_back(two_owners, settings):
    repo = two_owners
    bot = FakeBot()
    live = LiveBroadcaster(bot, repo, settings)
    await live.set_notify(OWNER_ID, True)
    await live.set_notify(OTHER_ID, True)
    await live.tick()

    await repo.add_operation(type="expense", amount=-12_000 * 100, category="Закуп",
                             created_by=OWNER_ID)
    await live.tick()

    assert [chat for chat, _ in bot.sent] == [OTHER_ID]
    assert "💸 −12 000 ₸ · Закуп" in bot.sent[0][1]


async def test_burst_is_grouped_into_one_message(two_owners, settings):
    repo = two_owners
    bot = FakeBot()
    live = LiveBroadcaster(bot, repo, settings)
    await live.set_notify(OWNER_ID, True)
    await live.tick()

    for n in range(NOTIFY_BATCH_LIMIT + 1):
        await _sale(repo, n, 1_000)
    await live.tick()

    assert len(bot.sent) == 1
    assert bot.sent[0][1].count("💰") == NOTIFY_BATCH_LIMIT + 1


async def test_unsubscribed_owner_gets_nothing(two_owners, settings):
    repo = two_owners
    bot = FakeBot()
    live = LiveBroadcaster(bot, repo, settings)
    await live.tick()
    await _sale(repo, 1, 1_000)
    await live.tick()
    assert bot.sent == []


async def test_board_is_pinned_and_edited_on_change(repo, settings):
    bot = FakeBot()
    live = LiveBroadcaster(bot, repo, settings)
    await live.enable_board(OWNER_ID)
    board_id = bot.sent[0]
    assert bot.pinned and bot.pinned[0][0] == OWNER_ID

    await live.tick()          # ничего не изменилось — правки нет
    assert bot.edited == []

    await _sale(repo, 1, 7_000)
    await live.tick()
    assert len(bot.edited) == 1
    assert "+7 000 ₸" in bot.edited[0][2]
    assert board_id[0] == OWNER_ID


async def test_deleted_board_switches_itself_off(repo, settings):
    bot = FakeBot()
    live = LiveBroadcaster(bot, repo, settings)
    await live.enable_board(OWNER_ID)
    bot.edit_error = RuntimeError("Bad Request: message to edit not found")

    await _sale(repo, 1, 1_000)
    await live.tick()

    assert not await live.board_enabled(OWNER_ID)


async def test_repo_feeds_several_listeners(repo):
    calls = []
    repo.set_change_listener(lambda: calls.append("sheets"))
    repo.add_change_listener(lambda: calls.append("live"))
    await _sale(repo, 1, 1_000)
    assert calls == ["sheets", "live"]
