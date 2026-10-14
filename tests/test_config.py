import pytest

from app.config import ConfigError, load_settings

BASE_ENV = {
    "BOT_TOKEN": "123:AA",
    "OWNER_TELEGRAM_IDS": "111",
}


def _apply(monkeypatch, **overrides):
    for key in list(BASE_ENV) + [
        "APIPAY_API_KEY", "APIPAY_WEBHOOK_SECRET", "APIPAY_SANDBOX", "APIPAY_BASE_URL",
        "TIMEZONE", "SUMMARY_TIME", "WEB_PORT", "SYNC_WINDOW_DAYS", "DB_PATH",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in {**BASE_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)
    return load_settings(env_file=None)


def test_defaults_follow_the_spec(monkeypatch):
    settings = _apply(monkeypatch)
    assert settings.timezone_name == "Asia/Almaty"
    assert (settings.summary_hour, settings.summary_minute) == (21, 0)
    assert settings.undo_window_minutes == 10
    assert settings.apipay_sandbox is False


def test_owner_ids_are_parsed_and_deduplicated(monkeypatch):
    settings = _apply(monkeypatch, OWNER_TELEGRAM_IDS="111, 222 ;111")
    assert settings.owner_ids == (111, 222)


def test_missing_bot_token_is_fatal(monkeypatch):
    with pytest.raises(ConfigError):
        _apply(monkeypatch, BOT_TOKEN="")


def test_empty_whitelist_is_fatal(monkeypatch):
    with pytest.raises(ConfigError):
        _apply(monkeypatch, OWNER_TELEGRAM_IDS=" , ")


@pytest.mark.parametrize("bad", ["21", "25:00", "21:70", "вечером"])
def test_bad_summary_time_is_fatal(monkeypatch, bad):
    with pytest.raises(ConfigError):
        _apply(monkeypatch, SUMMARY_TIME=bad)


def test_unknown_timezone_is_fatal(monkeypatch):
    with pytest.raises(ConfigError):
        _apply(monkeypatch, TIMEZONE="Mars/Olympus")


def test_apipay_disabled_without_key(monkeypatch):
    assert _apply(monkeypatch).apipay_enabled is False
    assert _apply(monkeypatch, APIPAY_API_KEY="k").apipay_enabled is True
