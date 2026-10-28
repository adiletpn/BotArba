"""Статистика ArbaFood: проценты, границы дня, текст."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.app_stats import AppStats, _day_bounds, percent, render_stats

ALMATY = ZoneInfo("Asia/Almaty")


def test_percent_keeps_small_shares_visible():
    assert percent(1669, 4394) == "38%"
    assert percent(3, 1669) == "0.2%", "иначе 3 заказа из 1669 показались бы как 0%"
    assert percent(0, 100) == "0%"
    assert percent(5, 0) == "—", "деления на ноль быть не должно"


def test_day_bounds_follow_almaty_not_utc():
    start, end = _day_bounds("2026-10-28", ALMATY)
    assert start.isoformat() == "2026-10-28T00:00:00+05:00"
    assert (end - start).total_seconds() == 86_400


def _stats(**kw):
    base = dict(day="2026-10-28", is_today=True,
                computed_at=datetime(2026, 10, 28, 14, 30, tzinfo=ALMATY),
                users_total=4394, users_active=1669, buyers=38, orders=41,
                orders_cancelled=3, new_users=17)
    base.update(kw)
    return AppStats(**base)


def test_render_today():
    text = render_stats(_stats()).replace(" ", " ")
    assert "сегодня, 28.10 14:30" in text
    assert "4 394" in text and "1 669  (38%)" in text
    assert "(2% активных)" in text
    assert "отменено 3" in text


def test_render_past_day_for_the_nightly_send():
    text = render_stats(_stats(day="2026-10-27", is_today=False, orders_cancelled=0))
    assert "итоги за 27.10.2026" in text
    assert "за день" in text
    assert "отменено" not in text, "строку отмен не показываем, если их не было"
