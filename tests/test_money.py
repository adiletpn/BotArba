import pytest

from app.money import AmountError, tiyn_from_api


def test_api_amount_with_cents_is_exact():
    assert tiyn_from_api("15000.00") == 1_500_000
    assert tiyn_from_api("190000.00") == 19_000_000
    assert tiyn_from_api("0.01") == 1


def test_api_amount_accepts_float_from_available_for_refund():
    # invoice.available_for_refund приходит числом, а не строкой
    assert tiyn_from_api(3000) == 300_000
    assert tiyn_from_api(3000.5) == 300_050


def test_api_amount_rejects_sub_tiyn_precision():
    with pytest.raises(AmountError):
        tiyn_from_api("100.001")


def test_api_amount_rejects_garbage():
    with pytest.raises(AmountError):
        tiyn_from_api("не число")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1000000", 100_000_000),
        ("1 000 000", 100_000_000),
        ("1 000 000 ₸", 100_000_000),
        ("100000тг", 10_000_000),
        ("1000000,50", 100_000_050),
        ("1000000.50", 100_000_050),
        ("  80000  ", 8_000_000),
    ],
)
def test_user_amount_accepts_real_world_input(raw, expected):
    from app.money import tiyn_from_user

    assert tiyn_from_user(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "0", "-500", "abc", "1.2.3", "1000.123"])
def test_user_amount_rejects_bad_input(raw):
    from app.money import tiyn_from_user

    with pytest.raises(AmountError):
        tiyn_from_user(raw)
