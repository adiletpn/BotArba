"""Выгрузка в Google Таблицы: снимок и отправка."""

from dataclasses import replace
from datetime import datetime, timezone

from app.services.sheets import DAILY_HEADER, OPERATIONS_HEADER, build_snapshot


async def test_snapshot_contains_operations_and_daily_totals(repo, settings):
    await repo.set_start_balance(100_000_000, created_by=1)
    await repo.add_operation(
        type="income", amount=19_000_000, source="apipay", external_id="invoice:42",
        occurred_at=datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc),
    )
    await repo.add_operation(
        type="expense", amount=-8_000_000, category="Закуп", created_by=1,
        occurred_at=datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc),
    )

    snapshot = await build_snapshot(repo, settings.timezone)

    assert snapshot["operations"]["header"] == list(OPERATIONS_HEADER)
    assert snapshot["daily"]["header"] == list(DAILY_HEADER)
    assert len(snapshot["operations"]["rows"]) == 3

    # Суммы в тенге, а не в тиынах: в таблице по ним считают
    amounts = [row[4] for row in snapshot["operations"]["rows"]]
    assert 190_000 in amounts
    assert -80_000 in amounts


async def test_cancelled_operations_stay_visible_but_out_of_totals(repo, settings):
    """Отменённый расход виден в журнале, но не искажает итоги дня."""
    await repo.add_operation(
        type="income", amount=5_000_000, source="apipay", external_id="invoice:1",
        occurred_at=datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc),
    )
    op_id = await repo.add_operation(
        type="expense", amount=-8_000_000, category="Закуп", created_by=1,
        occurred_at=datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc),
    )
    await repo.cancel_operation(op_id)

    snapshot = await build_snapshot(repo, settings.timezone)

    cancelled = [row for row in snapshot["operations"]["rows"] if row[-1] == "да"]
    assert len(cancelled) == 1, "отменённая операция остаётся в листе с пометкой"

    day = next(r for r in snapshot["daily"]["rows"] if r[0] == "13.10.2026")
    assert day[2] == 0, "но в расходы дня она не попадает"
    assert day[1] == 50_000, "поступление дня при этом на месте"


async def test_a_day_whose_only_operation_was_cancelled_disappears(repo, settings):
    """Пустой день в сводке не нужен: строка с нулями только путала бы."""
    op_id = await repo.add_operation(
        type="expense", amount=-8_000_000, category="Закуп", created_by=1,
        occurred_at=datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc),
    )
    await repo.cancel_operation(op_id)

    snapshot = await build_snapshot(repo, settings.timezone)

    assert snapshot["daily"]["rows"] == []
    assert len(snapshot["operations"]["rows"]) == 1, "сама операция в журнале остаётся"


async def test_daily_sheet_carries_a_running_balance(repo, settings):
    await repo.add_operation(
        type="start", amount=100_000_000, created_by=1,
        occurred_at=datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc),
    )
    await repo.add_operation(
        type="income", amount=5_000_000, source="apipay", external_id="invoice:1",
        occurred_at=datetime(2026, 10, 13, 6, 0, tzinfo=timezone.utc),
    )

    rows = (await build_snapshot(repo, settings.timezone))["daily"]["rows"]

    assert [row[0] for row in rows] == ["12.10.2026", "13.10.2026"]
    assert rows[0][5] == 1_000_000          # баланс на конец 12-го
    assert rows[1][5] == 1_050_000          # и на конец 13-го


async def _fake_apps_script(received: list, *, token: str):
    """Двойник веб-приложения Apps Script: та же проверка пароля и ответ."""
    from aiohttp import web

    async def handler(request: web.Request) -> web.Response:
        payload = await request.json()
        if payload.get("token") != token:
            return web.json_response({"error": "доступ запрещён"})
        received.append(payload)
        return web.json_response({
            "ok": True,
            "operations": len(payload["operations"]["rows"]),
            "daily": len(payload["daily"]["rows"]),
        })

    app = web.Application()
    app.router.add_post("/exec", handler)
    return app


async def test_snapshot_reaches_the_web_app(aiohttp_server, repo, settings):
    from app.services.sheets import sync

    received: list = []
    server = await aiohttp_server(await _fake_apps_script(received, token="s3cret"))
    configured = replace(
        settings,
        sheets_webapp_url=str(server.make_url("/exec")),
        sheets_token="s3cret",
    )

    await repo.set_start_balance(100_000_000, created_by=1)
    assert await sync(repo, configured) is True

    assert len(received) == 1
    assert received[0]["token"] == "s3cret"
    assert received[0]["operations"]["rows"][0][3] == "Старт"
    assert "generated_at" in received[0]


async def test_wrong_token_is_reported_as_failure(aiohttp_server, repo, settings):
    from app.services.sheets import sync

    received: list = []
    server = await aiohttp_server(await _fake_apps_script(received, token="s3cret"))
    configured = replace(
        settings,
        sheets_webapp_url=str(server.make_url("/exec")),
        sheets_token="неправильный",
    )

    assert await sync(repo, configured) is False
    assert received == [], "при неверном пароле данные не должны записываться"


async def test_sync_is_skipped_when_not_configured(repo, settings):
    from app.services.sheets import sync

    assert settings.sheets_enabled is False
    assert await sync(repo, settings) is False


async def test_html_error_page_is_not_mistaken_for_success(aiohttp_server, repo, settings):
    """Google при ошибке отдаёт HTML со статусом 200 — это не успех."""
    from aiohttp import web

    from app.services.sheets import sync

    async def handler(_: web.Request) -> web.Response:
        # В настоящей странице ошибки Google слово «cookie» есть почти всегда,
        # а в нём содержится подстрока «ok».
        return web.Response(
            text="<html><body>Enable cookies to continue</body></html>",
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_post("/exec", handler)
    server = await aiohttp_server(app)

    configured = replace(
        settings, sheets_webapp_url=str(server.make_url("/exec")), sheets_token="s3cret"
    )
    assert await sync(repo, configured) is False
