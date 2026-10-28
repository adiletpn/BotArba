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


async def test_snapshots_feed_the_sheet(repo, settings):
    from app.services.sheets import APP_STATS_HEADER, build_snapshot

    # прошлый день восстановлен задним числом — активных не знаем
    await repo.save_app_stats(day="2026-10-27", users_total=4389, users_active=None,
                              buyers=35, orders=40, orders_cancelled=5, new_users=53)
    await repo.save_app_stats(day="2026-10-28", users_total=4394, users_active=1669,
                              buyers=3, orders=3, orders_cancelled=0, new_users=5)

    block = (await build_snapshot(repo, settings.timezone))["app_stats"]
    assert block["header"] == list(APP_STATS_HEADER)
    past, today = block["rows"]
    assert past[0] == "27.10.2026" and past[2] == "" and past[3] == ""
    assert today[2] == 1669 and round(today[3], 2) == 0.38


async def test_backfill_never_erases_a_known_active_count(repo):
    """Пересчёт задним числом не должен затирать «активных», снятых вживую."""
    await repo.save_app_stats(day="2026-10-28", users_total=4394, users_active=1669,
                              buyers=3, orders=3, orders_cancelled=0, new_users=5)
    await repo.save_app_stats(day="2026-10-28", users_total=4394, users_active=None,
                              buyers=4, orders=4, orders_cancelled=0, new_users=5,
                              keep_active=True)
    (row,) = await repo.app_stats_rows()
    assert row["users_active"] == 1669
    assert row["orders"] == 4, "остальные цифры при этом обновились"


async def test_live_snapshot_replaces_the_same_day(repo):
    for orders in (3, 7):
        await repo.save_app_stats(day="2026-10-28", users_total=4394, users_active=1669,
                                  buyers=orders, orders=orders, orders_cancelled=0, new_users=5)
    rows = await repo.app_stats_rows()
    assert len(rows) == 1 and rows[0]["orders"] == 7


def test_credentials_accept_json_and_base64():
    import base64
    import json

    import pytest

    from app.services.app_stats import StatsError, parse_credentials

    info = {"type": "service_account", "project_id": "arbafood-taraz"}
    raw = json.dumps(info)
    assert parse_credentials(raw) == info
    assert parse_credentials(base64.b64encode(raw.encode()).decode()) == info

    # Ровно то, что получилось на Railway: переносы стали запятыми.
    broken = '{,  "type": "service_account",,  "project_id": "arbafood-taraz",}'
    with pytest.raises(StatsError):
        parse_credentials(broken)
