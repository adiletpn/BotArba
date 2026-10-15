"""Разбор даты для /day."""

from zoneinfo import ZoneInfo

from app.bot.handlers.settings import parse_day
from app.clock import shift_local_date, today_local

ALMATY = ZoneInfo("Asia/Almaty")


def test_explicit_dates():
    assert parse_day("14.10.2026", ALMATY) == "2026-10-14"
    assert parse_day("14/10/2026", ALMATY) == "2026-10-14"
    assert parse_day("14-10-26", ALMATY) == "2026-10-14"


def test_short_form_uses_the_current_year():
    today = today_local(ALMATY)
    assert parse_day("14.10", ALMATY).endswith("-10-14")
    assert parse_day("14.10", ALMATY)[:4] == today[:4]


def test_words():
    today = today_local(ALMATY)
    assert parse_day("", ALMATY) == today
    assert parse_day("сегодня", ALMATY) == today
    assert parse_day("вчера", ALMATY) == shift_local_date(today, -1)
    assert parse_day("ПОЗАВЧЕРА", ALMATY) == shift_local_date(today, -2)


def test_garbage_is_rejected():
    for raw in ("позапрошлый год", "32.13.2026", "14", "abc", "14.10.2026.5"):
        assert parse_day(raw, ALMATY) is None, raw
