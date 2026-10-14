"""Денежная арифметика.

Все суммы внутри приложения — целые числа в ТИЫНАХ (1 ₸ = 100 тиын).
Float не используется нигде: ApiPay отдаёт суммы строками вида "15000.00",
и единственный безопасный путь строка -> целое лежит через Decimal.

ТЗ разрешает хранить суммы «целыми числами в тенге (или в тиынах)». Выбраны
тиыны: округление до тенге на входе ломало бы инвариант «баланс = Σ операций»,
если Kaspi когда-нибудь отдаст счёт с копейками.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

TIYN_PER_TENGE = 100

#: Узкий неразрывный пробел для разрядов — не даёт Telegram рвать сумму по строкам.
GROUP_SEPARATOR = " "

TENGE_SIGN = "₸"


class AmountError(ValueError):
    """Сумму не удалось разобрать или она вне допустимого диапазона."""


#: Верхняя граница суммы одной операции — 10 млрд ₸.
#: Защищает от опечаток вида «1000000000000» и от переполнения в отчётах.
MAX_AMOUNT_TIYN = 10_000_000_000 * TIYN_PER_TENGE


def tiyn_from_api(value: str | int | float | Decimal) -> int:
    """Перевести сумму из ответа ApiPay в тиыны.

    ApiPay передаёт суммы строками ("15000.00"), но поле
    ``invoice.available_for_refund`` в вебхуке ``invoice.refunded`` приходит
    числом (float) — поэтому принимаем и его, конвертируя через str().
    """
    if isinstance(value, float):
        # str(float) даёт кратчайшее представление, которое round-trip'ится,
        # так что Decimal(str(1234.56)) == Decimal("1234.56") без мусорных хвостов.
        value = str(value)
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AmountError(f"Не удалось разобрать сумму ApiPay: {value!r}") from exc

    tiyn = (amount * TIYN_PER_TENGE).to_integral_value()
    if tiyn != amount * TIYN_PER_TENGE:
        raise AmountError(f"Сумма ApiPay точнее тиына: {value!r}")
    return int(tiyn)
