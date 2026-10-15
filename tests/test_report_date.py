"""За какой день отчитывается сводка.

В 00:00 начинается новый день, и сводка «за сегодня» показала бы нули.
Ночью отчитываемся за день, который только что закончился.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.bot.handlers.balance import report_date

ALMATY = ZoneInfo("Asia/Almaty")


def _at(hour: int, minute: int = 0, day: int = 15):
    """Момент по Алматы, приведённый к UTC — так его видит бот."""
    local = datetime(2026, 10, day, hour, minute, tzinfo=ALMATY)
    return local.astimezone(timezone.utc)


def test_midnight_reports_the_day_that_just_ended():
    assert report_date(_at(0, 0), ALMATY) == "2026-10-14"
    assert report_date(_at(0, 30), ALMATY) == "2026-10-14"
    assert report_date(_at(4, 59), ALMATY) == "2026-10-14"


def test_morning_and_later_report_today():
    assert report_date(_at(5, 0), ALMATY) == "2026-10-15"
    assert report_date(_at(12, 16), ALMATY) == "2026-10-15"
    assert report_date(_at(21, 0), ALMATY) == "2026-10-15"
    assert report_date(_at(23, 59), ALMATY) == "2026-10-15"


def test_the_balance_button_at_night_shows_the_finished_day_too():
    """Нажатие «Баланс» в час ночи — тот же вопрос: какой день показывать.

    Показываем вчерашний: в час ночи «итоги дня» для человека — это смена,
    которая только что закончилась, а не пустые первые 60 минут новых суток.
    """
    assert report_date(_at(1, 0), ALMATY) == "2026-10-14"
