"""Фильтры на русские слова.

Telegram разрешает в командах только латиницу, цифры и подчёркивание
(`/balance`), поэтому зарегистрировать `/баланс` в меню нельзя — это
ограничение платформы, а не бота. Но текст пользователь шлёт любой, и
ничто не мешает понимать обычные русские слова: «баланс», «расход»,
«история». Для человека это и есть «команда на русском».
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from aiogram.types import Message


def normalize(text: str | None) -> str:
    """Привести текст к сравнимому виду: только буквы, нижний регистр.

    Отбрасывает эмодзи, знаки и лишние пробелы, поэтому подпись кнопки
    «💰 Баланс» и набранное руками «баланс!» дают одно и то же.
    """
    letters = [ch if (ch.isalpha() or ch.isspace()) else " " for ch in (text or "").lower()]
    return " ".join("".join(letters).split())


def says(*phrases: str) -> Callable[[Message], bool]:
    """Фильтр «сообщение означает одно из этих слов»."""
    wanted = {normalize(phrase) for phrase in phrases}

    def _check(message: Message) -> bool:
        return normalize(message.text) in wanted

    return _check


def any_of(*groups: Iterable[str]) -> Callable[[Message], bool]:
    phrases: list[str] = []
    for group in groups:
        phrases.extend(group)
    return says(*phrases)
