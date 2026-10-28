"""Сборка бота и диспетчера."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

logger = logging.getLogger(__name__)

from app.bot.handlers import (
    balance,
    expense,
    history,
    manual,
    misc,
    settings as settings_handlers,
    start,
    stats,
)
from app.bot.middlewares import WhitelistMiddleware


def create_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))


#: Меню команд в Telegram. Регистрируется при старте, чтобы не настраивать
#: его руками в BotFather и не расходиться с тем, что реально реализовано.
#: Кнопки продублированы командами: в меню Telegram видно всё, что бот умеет,
#: и до любого действия можно добраться без клавиатуры.
BOT_COMMANDS = (
    BotCommand(command="start", description="Запуск и стартовый баланс"),
    BotCommand(command="balance", description="Баланс и сводка за сегодня"),
    BotCommand(command="stats", description="Пользователи и заказы ArbaFood"),
    BotCommand(command="expense", description="Внести расход"),
    BotCommand(command="history", description="Последние 10 операций"),
    BotCommand(command="day", description="Сводка за день, напр. /day 14.10"),
    BotCommand(command="income", description="Ручное поступление (админ)"),
    BotCommand(command="correct", description="Корректировка баланса (админ)"),
    BotCommand(command="reconcile", description="Сверить с Kaspi: /reconcile 1663000 (админ)"),
    BotCommand(command="settings", description="Настройки и время сводки"),
    BotCommand(command="settime", description="Сменить время сводки, напр. /settime 21:00"),
    BotCommand(command="export", description="Выгрузить в Google Таблицы сейчас"),
    BotCommand(command="whoami", description="Показать мой Telegram ID"),
    BotCommand(command="help", description="Что умеет бот"),
)


async def register_commands(bot: Bot) -> None:
    """Выставить меню команд и описание бота.

    Делается при каждом старте: так карточка бота всегда соответствует коду,
    и при переносе на другой токен ничего не нужно донастраивать руками.
    Ошибки здесь не критичны — бот работает и без описания.
    """
    from app.bot import texts

    await bot.set_my_commands(list(BOT_COMMANDS))

    # Имя и описание переписываем ТОЛЬКО если они изменились. Telegram жёстко
    # лимитирует setMyName — примерно раз в сутки, — а деплой на каждый коммит
    # вызывал бы его по десять раз подряд и упирался во Flood control.
    await _sync_profile_field(
        "имя",
        lambda: bot.get_my_name(),
        lambda current: current.name,
        texts.BOT_NAME,
        lambda value: bot.set_my_name(name=value),
    )
    await _sync_profile_field(
        "описание",
        lambda: bot.get_my_description(),
        lambda current: current.description,
        texts.BOT_DESCRIPTION,
        lambda value: bot.set_my_description(description=value),
    )
    await _sync_profile_field(
        "краткое описание",
        lambda: bot.get_my_short_description(),
        lambda current: current.short_description,
        texts.BOT_SHORT_DESCRIPTION,
        lambda value: bot.set_my_short_description(short_description=value),
    )


async def _sync_profile_field(label, read, extract, wanted, write) -> None:
    """Обновить одно поле профиля, если оно расходится с кодом.

    Ошибки не фатальны: бот прекрасно работает со старым описанием, а
    падать из-за косметики на старте он не должен.
    """
    try:
        current = extract(await read())
        if current == wanted:
            return
        await write(wanted)
        logger.info("Профиль бота: %s обновлено", label)
    except Exception as exc:
        logger.warning("Профиль бота: %s не обновлено (%s)", label, exc)


def create_dispatcher(repo, settings) -> Dispatcher:
    """Собрать диспетчер.

    Порядок роутеров значим: misc содержит перехватчик любого текста и обязан
    идти последним. repo и settings кладём в workflow_data — хендлеры получают
    их как обычные аргументы, без глобальных переменных.
    """
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["repo"] = repo
    dispatcher["settings"] = settings

    guard = WhitelistMiddleware(repo, settings.admin_ids)
    dispatcher.message.middleware(guard)
    dispatcher.callback_query.middleware(guard)

    from app.bot.handlers import undo

    dispatcher.include_routers(
        start.router,
        balance.router,
        stats.router,
        expense.router,
        undo.router,
        history.router,
        manual.router,
        settings_handlers.router,
        misc.router,
    )
    return dispatcher
