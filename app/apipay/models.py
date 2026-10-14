"""Модели данных ApiPay.

Разбираем только те поля, которые влияют на баланс. Остальное (корзина,
скидки, QR-ссылки) сознательно игнорируем: лишние поля — лишние причины
упасть на чужом релизе API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.clock import parse_utc_text
from app.money import tiyn_from_api

#: Статусы, в которых счёт УЖЕ принял деньги.
#: `partially_refunded` входит сюда обязательно: деньги по такому счёту получены,
#: и фильтр «покажи оплаченные» без него неполон (прямое предупреждение в спеке API).
PAID_STATUSES = ("paid", "partially_refunded")


@dataclass(frozen=True, slots=True)
class PaidInvoice:
    """Оплаченный счёт — источник поступления."""

    invoice_id: int
    amount: int               # тиыны
    refunded: int             # тиыны, уже возвращено по счёту
    paid_at: datetime
    is_sandbox: bool
    is_imported: bool         # продажа проведена в Kaspi Pay мимо ApiPay
    status: str

    @property
    def external_id(self) -> str:
        return f"invoice:{self.invoice_id}"

    @property
    def net_amount(self) -> int:
        """Сумма счёта за вычетом возвратов по нему."""
        return self.amount - self.refunded


def invoice_from_payload(payload: dict) -> PaidInvoice:
    """Собрать PaidInvoice из элемента GET /invoices или из вебхука.

    Формы совпадают по нужным нам полям, поэтому парсер один.
    `paid_at` отсутствует во всех статусах, кроме paid — вызывающий обязан
    отфильтровать неоплаченные счёта до вызова.
    """
    paid_at_raw = payload.get("paid_at")
    if not paid_at_raw:
        raise ValueError(f"У счёта {payload.get('id')} нет paid_at — он не оплачен")

    return PaidInvoice(
        invoice_id=int(payload["id"]),
        amount=tiyn_from_api(payload["amount"]),
        refunded=tiyn_from_api(payload.get("total_refunded") or "0"),
        paid_at=parse_utc_text(paid_at_raw),
        is_sandbox=bool(payload.get("is_sandbox", False)),
        is_imported=bool(payload.get("is_imported", False)),
        status=str(payload.get("status") or ""),
    )


@dataclass(frozen=True, slots=True)
class RefundEvent:
    """Возврат по счёту — уменьшает поступления за день."""

    refund_id: int
    invoice_id: int
    amount: int               # тиыны, положительное число
    status: str               # pending / processing / completed / failed
    created_at: datetime
    is_sandbox: bool
    error_code: str | None

    @property
    def external_id(self) -> str:
        return f"refund:{self.refund_id}"

    @property
    def is_completed(self) -> bool:
        """Только completed трогает баланс.

        Вебхук invoice.refunded приходит и на failed — такой возврат деньги
        не вернул, и вычитать его нельзя.
        """
        return self.status == "completed"


def refund_from_payload(payload: dict) -> RefundEvent:
    refund = payload["refund"]
    invoice = payload.get("invoice") or {}
    return RefundEvent(
        refund_id=int(refund["id"]),
        invoice_id=int(invoice.get("id") or 0),
        amount=tiyn_from_api(refund["amount"]),
        status=str(refund["status"]),
        created_at=parse_utc_text(refund["created_at"]),
        is_sandbox=bool(payload.get("is_sandbox", False)),
        error_code=refund.get("error_code"),
    )
