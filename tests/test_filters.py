"""Русские слова как команды."""

from aiogram.types import Message

from app.bot import texts
from app.bot.filters import normalize, says


def _message(text: str) -> Message:
    return Message.model_construct(message_id=1, text=text)


def test_normalize_strips_emoji_and_punctuation():
    assert normalize("💰 Баланс") == "баланс"
    assert normalize("  БАЛАНС!  ") == "баланс"
    assert normalize("Сколько   денег?") == "сколько денег"
    assert normalize(None) == ""


def test_button_label_and_typed_word_match_the_same_filter():
    check = says(*texts.SAY_BALANCE)
    assert check(_message(texts.BTN_BALANCE)) is True
    assert check(_message("баланс")) is True
    assert check(_message("Баланс")) is True
    assert check(_message("сколько денег")) is True


def test_unrelated_text_does_not_match():
    check = says(*texts.SAY_BALANCE)
    assert check(_message("закуп")) is False
    assert check(_message("балансир")) is False
    assert check(_message("")) is False


def test_every_action_has_distinct_words():
    """Одно слово не должно вести в два разных сценария."""
    groups = {
        "balance": texts.SAY_BALANCE, "expense": texts.SAY_EXPENSE,
        "history": texts.SAY_HISTORY, "income": texts.SAY_INCOME,
        "correct": texts.SAY_CORRECT, "settings": texts.SAY_SETTINGS,
        "export": texts.SAY_EXPORT, "help": texts.SAY_HELP,
    }
    seen: dict[str, str] = {}
    for action, phrases in groups.items():
        for phrase in phrases:
            word = normalize(phrase)
            assert word not in seen, f"{word!r} ведёт и в {seen.get(word)}, и в {action}"
            seen[word] = action


def test_button_labels_are_covered_by_their_words():
    assert says(*texts.SAY_BALANCE)(_message(texts.BTN_BALANCE))
    assert says(*texts.SAY_EXPENSE)(_message(texts.BTN_EXPENSE))
    assert says(*texts.SAY_HISTORY)(_message(texts.BTN_HISTORY))


def test_commands_escape_dialog_steps():
    """Баг из практики: /correct посреди ввода суммы получал «Не понял сумму»."""
    from app.bot.filters import not_command

    assert not_command(_message("100000")) is True
    assert not_command(_message("Закуп")) is True

    assert not_command(_message("/correct")) is False
    assert not_command(_message("/correct 1050000")) is False
    assert not_command(_message("  /start")) is False


def test_signed_amount_parsing():
    from app.bot.handlers.manual import parse_signed_amount

    assert parse_signed_amount("+50000") == 5_000_000
    assert parse_signed_amount("-50000") == -5_000_000
    assert parse_signed_amount("−50000") == -5_000_000
    # Без знака считаем, что имели в виду плюс
    assert parse_signed_amount("1050000") == 105_000_000
    assert parse_signed_amount("1 050 000 ₸") == 105_000_000

    assert parse_signed_amount("") is None
    assert parse_signed_amount("много") is None
