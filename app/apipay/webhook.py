"""Проверка и разбор вебхуков ApiPay."""

from __future__ import annotations

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Webhook-Signature"
SIGNATURE_PREFIX = "sha256="


def compute_signature(raw_body: bytes, secret: str) -> str:
    """HMAC-SHA256 от СЫРОГО тела запроса, ключ — webhook-секрет.

    Считать нужно именно по байтам запроса: пересериализованный JSON даст
    другую подпись (порядок ключей, пробелы, экранирование юникода).
    """
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(raw_body: bytes, header_value: str | None, secret: str) -> bool:
    """Сверить подпись. Пустой секрет означает «проверка отключена».

    Сравнение — compare_digest: побайтовое сравнение подписи утекает её
    через время ответа.
    """
    if not secret:
        return True
    if not header_value:
        logger.warning("Вебхук без заголовка %s", SIGNATURE_HEADER)
        return False
    return hmac.compare_digest(compute_signature(raw_body, secret), header_value.strip())


#: События, которые влияют на баланс. Остальные (подписки, чеки, смены кассы,
#: invoice.qr_scanned) приходят на тот же URL — отвечаем 200 и игнорируем.
HANDLED_EVENTS = ("invoice.status_changed", "invoice.refunded")


class IgnoredEvent(Exception):
    """Событие валидно, но нам не интересно. Отвечаем 200, ничего не пишем."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def event_name(payload: dict) -> str:
    return str(payload.get("event") or "")


def check_sandbox_flag(payload: dict, *, sandbox_mode: bool) -> None:
    """Отбросить события не из того режима, в котором работает бот.

    Спека ApiPay требует именно этого: в рабочем режиме событие с
    is_sandbox=true нужно принять (2xx) и не исполнять — песочное событие
    может долететь уже после перевода организации в прод.
    """
    is_sandbox = bool(payload.get("is_sandbox", False))
    if is_sandbox and not sandbox_mode:
        raise IgnoredEvent("событие из песочницы, а бот в рабочем режиме")
    if not is_sandbox and sandbox_mode:
        raise IgnoredEvent("рабочее событие, а бот в режиме песочницы")


def extract_paid_invoice(payload: dict):
    """Вытащить поступление из invoice.status_changed.

    Записываем только переход в оплаченный статус. Остальные статусы
    (pending/cancelled/expired/error) баланс не двигают.
    """
    from app.apipay.models import PAID_STATUSES, invoice_from_payload

    invoice = payload.get("invoice") or {}
    status = str(invoice.get("status") or "")
    if status not in PAID_STATUSES:
        raise IgnoredEvent(f"статус {status!r} не меняет баланс")
    if not invoice.get("paid_at"):
        raise IgnoredEvent(f"статус {status!r} без paid_at")

    # is_sandbox у объекта счёта может отличаться от флага события —
    # для разбора берём вложенный, он описывает сам счёт.
    invoice.setdefault("is_sandbox", payload.get("is_sandbox", False))
    return invoice_from_payload(invoice)


def extract_refund(payload: dict):
    """Вытащить возврат из invoice.refunded.

    Вебхук приходит и на failed — такой возврат деньги не вернул.
    """
    from app.apipay.models import refund_from_payload

    refund = refund_from_payload(payload)
    if not refund.is_completed:
        raise IgnoredEvent(
            f"возврат {refund.refund_id} в статусе {refund.status}"
            + (f" ({refund.error_code})" if refund.error_code else "")
        )
    return refund
