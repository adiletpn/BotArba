"""HTTP-клиент ApiPay.

Нужны всего две ручки: список оплаченных счетов за окно (страховка на случай
потерянного вебхука) и health-check. Счета бот не выставляет — он только
читает то, что уже оплачено.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from app.apipay.models import PAID_STATUSES, PaidInvoice, invoice_from_payload

logger = logging.getLogger(__name__)

#: Лимит ApiPay — 200 запросов/мин на ключ. Сверка раз в час укладывается
#: с огромным запасом, но таймаут всё равно нужен, чтобы сводка не зависла.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)

MAX_PER_PAGE = 100


class ApiPayError(RuntimeError):
    """ApiPay ответил ошибкой или не ответил.

    Для сводки это не фатально: ТЗ требует отправить её всё равно, с пометкой
    о времени последней успешной синхронизации.
    """


class ApiPayClient:
    def __init__(self, api_key: str, base_url: str = "https://api.apipay.kz/api/v1") -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "ApiPayClient":
        self._session = aiohttp.ClientSession(timeout=REQUEST_TIMEOUT)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=REQUEST_TIMEOUT)
        return self._session

    async def _get(self, path: str, params: list[tuple[str, str]] | None = None) -> dict:
        url = f"{self._base_url}{path}"
        session = self._ensure_session()
        try:
            async with session.get(
                url, params=params, headers={"X-API-Key": self._api_key}
            ) as response:
                if response.status >= 400:
                    body = (await response.text())[:500]
                    raise ApiPayError(f"{path} -> HTTP {response.status}: {body}")
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise ApiPayError(f"{path} недоступен: {exc}") from exc

    async def list_paid_invoices(
        self, date_from: str, date_to: str, *, include_sandbox: bool = False
    ) -> list[PaidInvoice]:
        """Оплаченные счета за окно, нарезанное по времени ОПЛАТЫ.

        Окно задаётся в зоне мерчанта (Asia/Almaty), как того ждёт API:
        голая дата = календарные сутки целиком.

        Два неочевидных параметра:
        * ``date_field=paid_at`` — резать по моменту оплаты, а не выставления:
          счёт, выставленный вчера и оплаченный сегодня, — сегодняшняя выручка.
        * ``origin=all`` — брать и продажи, проведённые в приложении Kaspi Pay
          мимо ApiPay (они подтягиваются из истории Kaspi, см. is_imported).
        """
        invoices: list[PaidInvoice] = []
        page = 1
        while True:
            params: list[tuple[str, str]] = [
                ("date_from", date_from),
                ("date_to", date_to),
                ("date_field", "paid_at"),
                ("origin", "all"),
                ("per_page", str(MAX_PER_PAGE)),
                ("page", str(page)),
            ]
            params += [("status[]", status) for status in PAID_STATUSES]

            payload = await self._get("/invoices", params)
            rows = payload.get("data") or []
            for row in rows:
                if not row.get("paid_at"):
                    continue
                if row.get("is_sandbox") and not include_sandbox:
                    continue
                try:
                    invoices.append(invoice_from_payload(row))
                except (ValueError, KeyError) as exc:
                    logger.warning("Счёт %s пропущен: %s", row.get("id"), exc)

            total = int(payload.get("total") or 0)
            if len(rows) < MAX_PER_PAGE or page * MAX_PER_PAGE >= total:
                return invoices
            page += 1

    async def is_healthy(self) -> bool:
        """GET /status — без авторизации, просто «API жив»."""
        try:
            await self._get("/status")
            return True
        except ApiPayError as exc:
            logger.warning("ApiPay недоступен: %s", exc)
            return False

    async def simulate_payment(self, invoice_id: int) -> dict:
        """Отметить sandbox-счёт оплаченным — для приёмки по ТЗ.

        Работает только в песочнице: в рабочем режиме ApiPay откажет. Порождает
        настоящий вебхук invoice.status_changed, так что путь проверяется целиком.
        """
        url = f"{self._base_url}/invoices/{invoice_id}/simulate-status"
        session = self._ensure_session()
        try:
            async with session.post(
                url, json={"status": "paid"}, headers={"X-API-Key": self._api_key}
            ) as response:
                body = await response.json(content_type=None)
                if response.status >= 400:
                    raise ApiPayError(f"simulate-status -> HTTP {response.status}: {body}")
                return body or {}
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise ApiPayError(f"simulate-status недоступен: {exc}") from exc
