"""Граница учёта: оплаты до стартовой суммы в неё уже входят.

Реальный случай: бота подключили к боевому аккаунту ApiPay, где за вчера
62 оплаты на 429 472 ₸. Без границы первая же сверка записала бы их все,
и баланс завысился бы на всю эту сумму — деньги уже лежат в стартовой.
"""

import json
from datetime import timedelta

from app.apipay.webhook import SIGNATURE_HEADER, compute_signature
from app.clock import now_utc, to_utc_text
from app.web.server import create_app


def _event(paid_at) -> dict:
    return {
        "event": "invoice.status_changed",
        "is_sandbox": True,
        "invoice": {
            "id": 900, "amount": "37299.00", "status": "paid",
            "is_sandbox": True, "paid_at": to_utc_text(paid_at),
            "client_phone": "87071234567",
        },
    }


async def _post(client, settings, payload):
    raw = json.dumps(payload, ensure_ascii=False).encode()
    return await client.post(
        settings.webhook_route, data=raw,
        headers={SIGNATURE_HEADER: compute_signature(raw, settings.apipay_webhook_secret),
                 "Content-Type": "application/json"},
    )


async def test_payment_before_the_start_balance_is_ignored(aiohttp_client, repo, settings):
    await repo.set_start_balance(100_000_000, created_by=1)
    client = await aiohttp_client(create_app(repo, settings))

    response = await _post(client, settings, _event(now_utc() - timedelta(days=1)))

    assert "ignored" in (await response.json())["outcome"]
    assert await repo.balance() == 100_000_000, "вчерашняя выручка уже в стартовой сумме"


async def test_payment_after_the_start_balance_is_recorded(aiohttp_client, repo, settings):
    await repo.set_start_balance(100_000_000, created_by=1)
    client = await aiohttp_client(create_app(repo, settings))

    response = await _post(client, settings, _event(now_utc()))

    assert (await response.json())["outcome"] == "income_recorded"
    assert await repo.balance() == 100_000_000 + 3_729_900


async def test_nothing_is_recorded_before_the_start_balance_exists(
    aiohttp_client, repo, settings
):
    """Без стартовой суммы не от чего считать — поступления не пишем."""
    client = await aiohttp_client(create_app(repo, settings))

    response = await _post(client, settings, _event(now_utc()))

    assert "ignored" in (await response.json())["outcome"]
    assert await repo.balance() == 0


async def test_unsigned_webhook_never_touches_the_balance(aiohttp_client, repo, settings):
    """Без секрета подписи адрес вебхука — открытая дверь. Не записываем ничего.

    Деньги при этом не теряются: часовая сверка подтянет оплату через API,
    где нас авторизует ключ.
    """
    from dataclasses import replace

    unprotected = replace(settings, apipay_webhook_secret="")
    await repo.set_start_balance(100_000_000, created_by=1)
    client = await aiohttp_client(create_app(repo, unprotected))

    raw = json.dumps(_event(now_utc())).encode()
    response = await client.post(
        unprotected.webhook_route, data=raw, headers={"Content-Type": "application/json"}
    )

    # 200, чтобы ApiPay не ретраил бесконечно, но в баланс ничего не идёт
    assert response.status == 200
    assert "ignored" in (await response.json())["outcome"]
    assert await repo.balance() == 100_000_000
