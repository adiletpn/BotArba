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
