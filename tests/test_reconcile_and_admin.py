"""Сверка с Kaspi и права администратора.

Реальный случай 15.10: стартовую сумму ввели «на глаз», 1 203 000 вместо
~1 364 000. Доходы и расходы бот считал верно, но баланс навсегда отставал
от счёта на 160 955 ₸. Лечение — одна сверка с проверенной цифрой Kaspi,
и запрет менять баланс всем, кроме администратора.
"""

import pytest

from app.bot import texts
from app.config import ConfigError, load_settings


# ---------- сверка ----------

async def test_reconcile_lands_exactly_on_the_kaspi_figure(repo):
    await repo.set_start_balance(120_300_000, created_by=1)      # 1 203 000 «на глаз»
    await repo.add_operation(type="income", amount=43_608_700, source="apipay",
                             external_id="invoice:1")
    await repo.add_operation(type="expense", amount=-13_704_200, category="Закуп",
                             created_by=1)
    assert await repo.balance() == 150_204_500                    # 1 502 045

    delta = await repo.align_balance_to(166_300_000, comment="Сверка", created_by=1)

    assert delta == 16_095_500                                     # +160 955 ₸
    assert await repo.balance() == 166_300_000                     # ровно 1 663 000


async def test_reconcile_can_go_down_too(repo):
    await repo.set_start_balance(200_000_000, created_by=1)
    delta = await repo.align_balance_to(150_000_000, comment="Сверка", created_by=1)
    assert delta == -50_000_000
    assert await repo.balance() == 150_000_000


async def test_reconcile_writes_nothing_when_already_equal(repo):
    await repo.set_start_balance(100_000_000, created_by=1)
    assert await repo.align_balance_to(100_000_000, comment="Сверка", created_by=1) is None
    assert len(await repo.recent_operations(10)) == 1, "пустой поправки быть не должно"


async def test_reconcile_keeps_history_intact(repo):
    """Старт не перезаписывается — сверка добавляет отдельную строку."""
    await repo.set_start_balance(120_300_000, created_by=1)
    await repo.align_balance_to(136_395_500, comment="Сверка с Kaspi", created_by=1)

    ops = await repo.recent_operations(10)
    kinds = sorted(op.type for op in ops)
    assert kinds == ["correction", "start"]
    start = next(op for op in ops if op.type == "start")
    assert start.amount == 120_300_000, "исходная стартовая сумма осталась как была"


# ---------- права ----------

class _Message:
    """Минимальный двойник Message: собирает ответы бота."""

    def __init__(self) -> None:
        self.replies: list[str] = []

    async def answer(self, text, **_):
        self.replies.append(text)


class _State:
    async def clear(self): ...
    async def set_state(self, *_): ...
    async def update_data(self, **_): ...


@pytest.mark.parametrize("handler_path", [
    "app.bot.handlers.manual:income_start",
    "app.bot.handlers.manual:correct_start",
])
async def test_non_admin_cannot_change_the_balance(handler_path):
    import importlib

    module, name = handler_path.split(":")
    handler = getattr(importlib.import_module(module), name)
    message = _Message()

    await handler(message, _State(), is_admin=False)

    assert message.replies == [texts.ADMIN_ONLY]


async def test_non_admin_cannot_reconcile(repo):
    from app.bot.handlers.manual import reconcile_with_kaspi

    await repo.set_start_balance(100_000_000, created_by=1)
    message = _Message()

    class _Cmd:
        args = "999999999"

    await reconcile_with_kaspi(message, _State(), repo, 1, _Cmd(), is_admin=False)

    assert message.replies == [texts.ADMIN_ONLY]
    assert await repo.balance() == 100_000_000, "баланс не должен сдвинуться"


async def test_non_admin_is_not_asked_for_the_start_balance(repo, settings):
    from app.bot.handlers.start import cmd_start

    message = _Message()

    class _M(_Message):
        pass

    await cmd_start(message, _State(), repo, settings, is_admin=False)

    assert texts.START_BALANCE_BY_ADMIN in message.replies
    assert texts.ASK_START_BALANCE not in message.replies


# ---------- конфиг ----------

def _env(monkeypatch, **values):
    for key in ("BOT_TOKEN", "OWNER_TELEGRAM_IDS", "ADMIN_TELEGRAM_IDS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return load_settings(env_file=None)


def test_admins_default_to_all_owners(monkeypatch):
    s = _env(monkeypatch, BOT_TOKEN="1:a", OWNER_TELEGRAM_IDS="1,2,3")
    assert s.admin_ids == (1, 2, 3)


def test_admins_can_be_narrowed(monkeypatch):
    s = _env(monkeypatch, BOT_TOKEN="1:a", OWNER_TELEGRAM_IDS="1,2,3",
             ADMIN_TELEGRAM_IDS="2")
    assert s.admin_ids == (2,)


def test_admin_must_be_whitelisted(monkeypatch):
    with pytest.raises(ConfigError):
        _env(monkeypatch, BOT_TOKEN="1:a", OWNER_TELEGRAM_IDS="1,2",
             ADMIN_TELEGRAM_IDS="99")
