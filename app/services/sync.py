"""Сверка с ApiPay — страховка на случай потерянного вебхука.

ТЗ: «раз в час и перед вечерней сводкой бот опрашивает API ApiPay за текущий
день и досоздаёт пропущенные оплаты».

Окно берём шире одного дня, и вот почему: продажи, проведённые в приложении
Kaspi Pay мимо ApiPay, подтягиваются из истории Kaspi не мгновенно и
датируются временем самой операции — то есть появляются ВНУТРИ уже пройденного
периода. Спека ApiPay прямо требует перезапрашивать окно, а не только новые
записи.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.apipay.client import ApiPayClient, ApiPayError
from app.clock import now_utc, shift_local_date, today_local

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncResult:
    ok: bool
    invoices_seen: int = 0
    income_added: int = 0
    refunds_added: int = 0
    error: str | None = None


async def reconcile(
    repo, client: ApiPayClient, settings, *, window_days: int | None = None
) -> SyncResult:
    """Догнать поступления и возвраты из ApiPay за окно.

    Идемпотентность держится на external_id: повторная сверка тех же счетов
    не добавляет ни одной строки, поэтому запускать её можно сколь угодно часто.
    """
    days = window_days or settings.sync_window_days
    today = today_local(settings.timezone)
    date_from = shift_local_date(today, -(days - 1))

    try:
        invoices = await client.list_paid_invoices(
            date_from, today, include_sandbox=settings.apipay_sandbox
        )
    except ApiPayError as exc:
        # Сводка должна уйти даже при недоступном ApiPay — с пометкой о
        # времени последней успешной сверки. Поэтому ошибку возвращаем, а не бросаем.
        logger.warning("Сверка с ApiPay не удалась: %s", exc)
        return SyncResult(ok=False, error=str(exc))

    income_added = refunds_added = 0
    for invoice in invoices:
        # Поступление пишем ГРОССОМ: возврат — отдельная операция, иначе
        # в истории исчез бы сам факт возврата.
        operation_id = await repo.add_operation(
            type="income",
            amount=invoice.amount,
            comment="Kaspi / ApiPay" + (" (мимо ApiPay)" if invoice.is_imported else ""),
            source="apipay",
            external_id=invoice.external_id,
            occurred_at=invoice.paid_at,
        )
        if operation_id is not None:
            income_added += 1
            logger.info("Досоздана оплата %s на %s тиын", invoice.invoice_id, invoice.amount)

        if invoice.refunded:
            if await _sync_refund_total(repo, invoice.invoice_id, invoice.refunded):
                refunds_added += 1

    await repo.mark_apipay_sync(now_utc())
    return SyncResult(
        ok=True, invoices_seen=len(invoices),
        income_added=income_added, refunds_added=refunds_added,
    )


async def _sync_refund_total(repo, invoice_id: int, api_total: int) -> bool:
    """Догнать возвраты по счёту до суммы, которую показывает ApiPay.

    Пишем РАЗНИЦУ между тем, что в ApiPay, и тем, что уже записано: вебхук
    приходит на каждый возврат отдельно, а список счетов отдаёт только
    накопленный total_refunded. Ключ строки включает накопленную сумму,
    поэтому повторная сверка того же состояния ничего не добавит.
    """
    recorded = await repo.refunded_total_for_invoice(invoice_id)
    delta = api_total - recorded
    if delta <= 0:
        return False

    operation_id = await repo.add_operation(
        type="refund",
        amount=-delta,
        comment=f"Возврат по счёту {invoice_id} (сверка)",
        source="apipay",
        external_id=f"refund:{invoice_id}:total:{api_total}",
    )
    if operation_id is None:
        return False
    logger.info("Досоздан возврат по счёту %s на %s тиын", invoice_id, delta)
    return True


async def record_webhook_refund(repo, refund) -> int | None:
    """Записать возврат, пришедший вебхуком.

    Ключ согласован со сверкой по префиксу "refund:<invoice_id>:", чтобы
    часовая сверка видела эту строку и не задваивала возврат.
    """
    return await repo.add_operation(
        type="refund",
        amount=-refund.amount,
        comment=f"Возврат по счёту {refund.invoice_id}",
        source="apipay",
        external_id=f"refund:{refund.invoice_id}:{refund.refund_id}",
        occurred_at=refund.created_at,
    )
