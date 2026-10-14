from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.clock import (
    format_date_ru,
    format_time_local,
    local_date_of,
    parse_utc_text,
    shift_local_date,
    to_utc_text,
)

ALMATY = ZoneInfo("Asia/Almaty")


def test_late_evening_payment_stays_in_the_merchant_day():
    # 13.10.2026 20:30 по Алматы = 15:30 UTC. День должен остаться 13-м.
    moment = datetime(2026, 10, 13, 15, 30, tzinfo=timezone.utc)
    assert local_date_of(moment, ALMATY) == "2026-10-13"


def test_payment_just_after_midnight_belongs_to_the_new_day():
    # 14.10.2026 00:10 по Алматы = 13.10 19:10 UTC.
    moment = datetime(2026, 10, 13, 19, 10, tzinfo=timezone.utc)
    assert local_date_of(moment, ALMATY) == "2026-10-14"


def test_utc_text_round_trips():
    moment = datetime(2026, 10, 13, 15, 30, tzinfo=timezone.utc)
    assert parse_utc_text(to_utc_text(moment)) == moment


def test_apipay_timestamps_are_parsed():
    assert parse_utc_text("2026-02-12T14:35:00+00:00").hour == 14
    assert parse_utc_text("2026-02-12T14:35:00Z").hour == 14
    # Момент в зоне +05:00 приводится к UTC
    assert parse_utc_text("2026-02-12T19:35:00+05:00").hour == 14


def test_display_helpers():
    assert format_date_ru("2026-10-13") == "13.10.2026"
    moment = datetime(2026, 10, 13, 13, 40, tzinfo=timezone.utc)
    assert format_time_local(moment, ALMATY) == "18:40"
    assert shift_local_date("2026-10-01", -1) == "2026-09-30"
