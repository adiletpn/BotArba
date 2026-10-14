"""Критерии приёмки из ТЗ, прогнанные через настоящий HTTP-эндпоинт вебхука."""

import json

from app.apipay.webhook import SIGNATURE_HEADER, compute_signature
from app.web.server import create_app

START_BALANCE = 100_000_000      # 1 000 000 ₸
PAYMENT = 19_000_000             #   190 000 ₸
EXPENSE = 10_000_000             #   100 000 ₸

PAID_WEBHOOK = {
    "event": "invoice.status_changed",
    "is_sandbox": True,
    "invoice": {
        "id": 777,
        "amount": "190000.00",
        "status": "paid",
        "kaspi_invoice_id": "13234689513",
        "client_phone": "87071234567",
        "is_sandbox": True,
        "kaspi_sale_type": "Remote",
        "paid_at": "2026-10-13T09:00:00+00:00",
    },
}


async def _post_webhook(client, settings, payload: dict):
    """Отправить вебхук так, как его шлёт ApiPay: с подписью по сырому телу."""
    raw = json.dumps(payload, ensure_ascii=False).encode()
    return await client.post(
        settings.webhook_route,
        data=raw,
        headers={
            SIGNATURE_HEADER: compute_signature(raw, settings.apipay_webhook_secret),
            "Content-Type": "application/json",
        },
    )


async def test_sandbox_payment_lands_in_the_balance(aiohttp_client, repo, settings):
    """190 000 ₸ из песочницы -> баланс 1 190 000 ₸."""
    await repo.set_start_balance(START_BALANCE, created_by=1)
    client = await aiohttp_client(create_app(repo, settings))

    response = await _post_webhook(client, settings, PAID_WEBHOOK)
    assert response.status == 200
    assert (await response.json())["outcome"] == "income_recorded"

    assert await repo.balance() == START_BALANCE + PAYMENT == 119_000_000


async def test_replayed_webhook_does_not_double_the_balance(aiohttp_client, repo, settings):
    """Критерий: повторная отправка того же вебхука не удваивает сумму."""
    await repo.set_start_balance(START_BALANCE, created_by=1)
    client = await aiohttp_client(create_app(repo, settings))

    for _ in range(3):
        response = await _post_webhook(client, settings, PAID_WEBHOOK)
        assert response.status == 200

    assert await repo.balance() == 119_000_000


async def test_forged_webhook_is_rejected_and_logged(aiohttp_client, repo, settings):
    client = await aiohttp_client(create_app(repo, settings))
    raw = json.dumps(PAID_WEBHOOK).encode()

    response = await client.post(
        settings.webhook_route, data=raw,
        headers={SIGNATURE_HEADER: "sha256=deadbeef", "Content-Type": "application/json"},
    )

    assert response.status == 401
    assert await repo.balance() == 0

    async with repo._db.conn.execute(
        "SELECT outcome, signature_ok FROM webhook_logs ORDER BY id DESC LIMIT 1"
    ) as cursor:
        row = await cursor.fetchone()
    assert row["outcome"] == "bad_signature"
    assert row["signature_ok"] == 0


async def test_every_webhook_is_written_to_the_log(aiohttp_client, repo, settings):
    """ТЗ: все входящие вебхуки пишутся в лог, чтобы разобрать спорный случай."""
    client = await aiohttp_client(create_app(repo, settings))
    await _post_webhook(client, settings, PAID_WEBHOOK)
    await _post_webhook(client, settings, {"event": "subscription.created", "is_sandbox": True})

    async with repo._db.conn.execute("SELECT COUNT(*) AS cnt FROM webhook_logs") as cursor:
        row = await cursor.fetchone()
    assert row["cnt"] == 2


async def test_expense_and_undo_restore_the_balance(aiohttp_client, repo, settings):
    """Расход 100 000 -> 1 090 000; «Отменить» -> 1 190 000."""
    await repo.set_start_balance(START_BALANCE, created_by=1)
    client = await aiohttp_client(create_app(repo, settings))
    await _post_webhook(client, settings, PAID_WEBHOOK)
    assert await repo.balance() == 119_000_000

    operation_id = await repo.add_operation(
        type="expense", amount=-EXPENSE, category="Закуп", created_by=1
    )
    assert await repo.balance() == 109_000_000     # 1 090 000 ₸

    assert await repo.cancel_operation(operation_id) is True
    assert await repo.balance() == 119_000_000     # 1 190 000 ₸


async def test_refund_reduces_the_day_income(aiohttp_client, repo, settings):
    await repo.set_start_balance(START_BALANCE, created_by=1)
    client = await aiohttp_client(create_app(repo, settings))
    await _post_webhook(client, settings, PAID_WEBHOOK)

    refund_event = {
        "event": "invoice.refunded",
        "is_sandbox": True,
        "refund": {"id": 9, "amount": "20000.00", "status": "completed",
                   "created_at": "2026-10-13T10:00:00+00:00"},
        "invoice": {"id": 777, "amount": "190000.00", "total_refunded": "20000.00",
                    "is_fully_refunded": False, "status": "partially_refunded"},
    }
    response = await _post_webhook(client, settings, refund_event)
    assert (await response.json())["outcome"] == "refund_recorded"

    assert await repo.balance() == 119_000_000 - 2_000_000

    totals = await repo.day_totals("2026-10-13")
    # Возврат уменьшает поступления за день, а не добавляется в расходы
    assert totals["income"] == PAYMENT - 2_000_000
    assert totals["expense"] == 0


async def test_balance_and_history_survive_a_restart(repo, settings):
    """Критерий: после перезапуска сервера баланс и история сохраняются."""
    from app.db.database import Database
    from app.db.repo import Repo

    await repo.set_start_balance(START_BALANCE, created_by=1)
    await repo.add_operation(type="expense", amount=-EXPENSE, category="Закуп", created_by=1)
    path = repo._db._path
    await repo._db.close()

    # Новый процесс: открываем ту же базу с нуля.
    reopened_db = Database(path)
    await reopened_db.connect()
    await reopened_db.init_schema()
    reopened = Repo(reopened_db, settings.timezone)

    assert await reopened.balance() == 90_000_000
    assert len(await reopened.recent_operations(10)) == 2
    await reopened_db.close()
