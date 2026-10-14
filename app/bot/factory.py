"""Сборка бота и диспетчера."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.bot.handlers import (
    balance,
    expense,
    history,
    manual,
    misc,
    settings as settings_handlers,
    start,
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
    BotCommand(command="expense", description="Внести расход"),
    BotCommand(command="history", description="Последние 10 операций"),
    BotCommand(command="income", description="Ручное поступление (наличные, перевод)"),
    BotCommand(command="correct", description="Корректировка баланса"),
    BotCommand(command="settings", description="Настройки и время сводки"),
    BotCommand(command="settime", description="Сменить время сводки, напр. /settime 21:00"),
    BotCommand(command="export", description="Выгрузить в Google Таблицы сейчас"),
    BotCommand(command="whoami", description="Показать мой Telegram ID"),
    BotCommand(command="help", description="Что умеет бот"),
)


async def register_commands(bot: Bot) -> None:
    await bot.set_my_commands(list(BOT_COMMANDS))


def create_dispatcher(repo, settings) -> Dispatcher:
    """Собрать диспетчер.

    Порядок роутеров значим: misc содержит перехватчик любого текста и обязан
    идти последним. repo и settings кладём в workflow_data — хендлеры получают
    их как обычные аргументы, без глобальных переменных.
    """
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["repo"] = repo
    dispatcher["settings"] = settings

    guard = WhitelistMiddleware(repo)
    dispatcher.message.middleware(guard)
    dispatcher.callback_query.middleware(guard)

    from app.bot.handlers import undo

    dispatcher.include_routers(
        start.router,
        balance.router,
        expense.router,
        undo.router,
        history.router,
        manual.router,
        settings_handlers.router,
        misc.router,
    )
    return dispatcher
