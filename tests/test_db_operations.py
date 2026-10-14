from datetime import datetime, timezone

from app.money import tiyn_from_user


async def test_balance_is_the_sum_of_operations(repo):
    assert await repo.balance() == 0

    await repo.set_start_balance(tiyn_from_user("1000000"), created_by=1)
    assert await repo.balance() == 100_000_000

    await repo.add_operation(type="income", amount=19_000_000, source="apipay",
                             external_id="invoice:42")
    assert await repo.balance() == 119_000_000

    await repo.add_operation(type="expense", amount=-10_000_000, category="Закуп")
    assert await repo.balance() == 109_000_000


async def test_cancelling_an_expense_restores_the_balance(repo):
    await repo.set_start_balance(119_000_000, created_by=1)
    op_id = await repo.add_operation(type="expense", amount=-10_000_000, category="Закуп")

    assert await repo.balance() == 109_000_000
    assert await repo.cancel_operation(op_id) is True
    assert await repo.balance() == 119_000_000

    # Повторная отмена ничего не меняет — кнопку могли нажать дважды.
    assert await repo.cancel_operation(op_id) is False
    assert await repo.balance() == 119_000_000


async def test_start_of_day_balance_ignores_today(repo):
    await repo.add_operation(
        type="income", amount=5_000_000, source="apipay", external_id="invoice:1",
        occurred_at=datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc),
    )
    await repo.add_operation(
        type="income", amount=7_000_000, source="apipay", external_id="invoice:2",
        occurred_at=datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc),
    )
    assert await repo.balance_before("2026-10-13") == 5_000_000
    assert await repo.balance() == 12_000_000
