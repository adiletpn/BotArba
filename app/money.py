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


def tiyn_from_user(text: str) -> int:
    """Разобрать сумму, введённую пользователем в чате.

    Принимаем то, как люди реально пишут суммы: "1000000", "1 000 000",
    "1 000 000 ₸", "1000000.50", "1000000,50", "100 000тг".
    Отрицательные значения не принимаем: знак задаёт тип операции, не сумма.
    """
    if text is None:
        raise AmountError("Пустая сумма")

    cleaned = text.strip().lower()
    for junk in (TENGE_SIGN, "тг", "тенге", "kzt", "т."):
        cleaned = cleaned.replace(junk, "")
    # Пробелы (включая неразрывные) и апострофы — разделители разрядов.
    for space in (" ", " ", " ", "'", "_"):
        cleaned = cleaned.replace(space, "")
    cleaned = cleaned.replace(",", ".").strip()

    if not cleaned:
        raise AmountError("Пустая сумма")
    if cleaned.count(".") > 1:
        raise AmountError("Слишком много разделителей в сумме")
    if not cleaned.replace(".", "").isdigit():
        raise AmountError("Сумма должна быть числом")

    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise AmountError("Сумма должна быть числом") from exc

    if amount <= 0:
        raise AmountError("Сумма должна быть больше нуля")

    tiyn = amount * TIYN_PER_TENGE
    if tiyn != tiyn.to_integral_value():
        raise AmountError("Сумма точнее тиына — максимум два знака после запятой")

    result = int(tiyn)
    if result > MAX_AMOUNT_TIYN:
        raise AmountError("Сумма слишком большая")
    return result


def format_tenge(tiyn: int, *, with_sign_symbol: bool = True) -> str:
    """Показать сумму в тенге: "1 000 000 ₸".

    Копейки печатаются только если они не нулевые (требование ТЗ).
    Знак минуса — типографский U+2212, как в образцах сообщений из ТЗ.
    """
    negative = tiyn < 0
    whole, remainder = divmod(abs(int(tiyn)), TIYN_PER_TENGE)

    grouped = f"{whole:,}".replace(",", GROUP_SEPARATOR)
    if remainder:
        grouped = f"{grouped},{remainder:02d}"

    out = f"−{grouped}" if negative else grouped
    return f"{out}{GROUP_SEPARATOR}{TENGE_SIGN}" if with_sign_symbol else out


def format_delta(tiyn: int) -> str:
    """Сумма со явным знаком: "+190 000 ₸" / "−100 000 ₸".

    Используется в строках «Поступления» и «Расходы» сводки, где знак несёт
    смысл движения, а не отрицательности самого числа.
    """
    if tiyn == 0:
        return format_tenge(0)
    if tiyn > 0:
        return f"+{format_tenge(tiyn)}"
    return format_tenge(tiyn)
