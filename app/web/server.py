"""HTTP-сервер: вебхук ApiPay и health-check.

Почему вообще нужен веб-сервер: ApiPay сообщает об оплате вебхуком, а значит
боту нужен публичный HTTPS-адрес. Бот при этом работает на long polling —
telegram-вебхук тут не используется, чтобы один упавший URL не ломал сразу
и оплаты, и управление.
"""

from __future__ import annotations

import json
import logging

from aiohttp import web

from app.apipay.models import PaidInvoice
from app.apipay.webhook import (
    HANDLED_EVENTS,
    SIGNATURE_HEADER,
    IgnoredEvent,
    check_sandbox_flag,
    event_name,
    extract_paid_invoice,
    extract_refund,
    verify_signature,
)
from app.services.sync import record_webhook_refund

logger = logging.getLogger(__name__)


async def _handle_payload(
    repo, payload: dict, sandbox_mode: bool, *, trusted: bool = True
) -> str:
    """Применить событие к балансу. Вернуть строку исхода для журнала.

    ``trusted=False`` означает, что подпись не проверялась (секрет не настроен).
    Такое событие в баланс не попадает: адрес вебхука публичный, и без подписи
    кто угодно может прислать поддельное поступление. Деньги всё равно не
    потеряются — часовая сверка подтянет оплату через API, где нас авторизует
    ключ.
    """
    if not trusted:
        raise IgnoredEvent(
            "подпись не проверена: APIPAY_WEBHOOK_SECRET не задан. "
            "Оплата будет учтена часовой сверкой"
        )

    name = event_name(payload)
    if name not in HANDLED_EVENTS:
        raise IgnoredEvent(f"событие {name!r} баланс не меняет")

    check_sandbox_flag(payload, sandbox_mode=sandbox_mode)

    # Та же граница, что и в сверке: оплата до стартовой суммы уже учтена в ней.
    cutoff = await repo.start_balance_moment()
    if cutoff is None:
        raise IgnoredEvent("стартовая сумма ещё не задана")

    if name == "invoice.status_changed":
        invoice: PaidInvoice = extract_paid_invoice(payload)
        if invoice.paid_at < cutoff:
            raise IgnoredEvent("оплата прошла до стартовой суммы")
        operation_id = await repo.add_operation(
            type="income",
            amount=invoice.amount,
            comment="Kaspi / ApiPay" + (" (мимо ApiPay)" if invoice.is_imported else ""),
            source="apipay",
            external_id=invoice.external_id,
            occurred_at=invoice.paid_at,
        )
        if operation_id is None:
            # Повторный вебхук: ApiPay ретраит доставку, и это норма.
            return "duplicate"
        logger.info("Оплата %s на %s тиын записана", invoice.invoice_id, invoice.amount)
        return "income_recorded"

    refund = extract_refund(payload)
    # Возврат сравниваем по СВОЕЙ дате, а не по дате счёта: деньги уходят
    # сейчас, даже если счёт был оплачен до начала учёта.
    if refund.created_at < cutoff:
        raise IgnoredEvent("возврат прошёл до стартовой суммы")
    operation_id = await record_webhook_refund(repo, refund)
    if operation_id is None:
        return "duplicate"
    logger.info("Возврат %s на %s тиын записан", refund.refund_id, refund.amount)
    return "refund_recorded"


def create_app(repo, settings, scheduler=None) -> web.Application:
    """Собрать aiohttp-приложение с вебхуком и health-check."""

    async def webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        signature = request.headers.get(SIGNATURE_HEADER)

        signature_ok = verify_signature(raw, signature, settings.apipay_webhook_secret)
        body_text = raw.decode("utf-8", errors="replace")

        if not signature_ok:
            # ТЗ требует логировать ВСЕ входящие вебхуки, включая отвергнутые.
            await repo.log_webhook(
                body=body_text, status_code=401, outcome="bad_signature",
                signature_ok=False,
            )
            logger.warning("Вебхук с неверной подписью отклонён")
            return web.json_response({"error": "invalid signature"}, status=401)

        try:
            payload = json.loads(body_text)
            if not isinstance(payload, dict):
                raise ValueError("ожидался JSON-объект")
        except ValueError as exc:
            await repo.log_webhook(
                body=body_text, status_code=400, outcome=f"bad_json: {exc}",
                signature_ok=True,
            )
            return web.json_response({"error": "invalid json"}, status=400)

        try:
            outcome = await _handle_payload(
                repo, payload, settings.apipay_sandbox,
                trusted=bool(settings.apipay_webhook_secret),
            )
        except IgnoredEvent as ignored:
            outcome = f"ignored: {ignored.reason}"
        except Exception:
            # Падение внутри обработки не должно выглядеть для ApiPay как
            # «доставлено»: 500 заставит его повторить, а дубликат нам не страшен.
            logger.exception("Ошибка обработки вебхука")
            await repo.log_webhook(
                body=body_text, status_code=500, outcome="handler_error",
                event=event_name(payload), signature_ok=True,
            )
            return web.json_response({"error": "internal"}, status=500)

        await repo.log_webhook(
            body=body_text,
            status_code=200,
            outcome=outcome,
            event=event_name(payload),
            invoice_id=str((payload.get("invoice") or {}).get("id") or ""),
            signature_ok=True,
            is_sandbox=bool(payload.get("is_sandbox", False)),
        )
        return web.json_response({"status": "ok", "outcome": outcome})

    async def health(_: web.Request) -> web.Response:
        """Railway дергает этот путь, чтобы понять, что контейнер жив.

        Заодно отдаём расписание: время следующего запуска — единственный
        способ снаружи убедиться, что задания считают время в нужной зоне.
        """
        body = {"status": "ok", "balance_ops": await repo.balance()}
        if scheduler is not None:
            body["jobs"] = {
                job.id: job.next_run_time.astimezone(settings.timezone).isoformat()
                for job in scheduler.get_jobs()
                if job.next_run_time
            }
        return web.json_response(body)

    app = web.Application()
    app.router.add_post(settings.webhook_route, webhook)
    app.router.add_get("/health", health)
    return app
