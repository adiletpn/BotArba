"""«Остаток на начало дня»: ТЗ — «в первый день это стартовая сумма»."""

from datetime import datetime, timezone

from app.clock import today_local
from app.services.summary import build_day_summary


async def test_first_day_opening_equals_the_start_balance(repo, settings):
    await repo.set_start_balance(100_000_000, created_by=1)
    today = today_local(settings.timezone)

    summary = await build_day_summary(repo, today)

    assert summary.opening == 100_000_000, "в первый день остаток на начало = стартовая сумма"
    assert summary.income == 0, "стартовая сумма — не поступление дня"
    assert summary.balance == 100_000_000


async def test_first_day_summary_adds_up(repo, settings):
    """Строки сводки должны сходиться между собой, иначе ей нельзя верить."""
    await repo.set_start_balance(100_000_000, created_by=1)
    await repo.add_operation(type="income", amount=19_000_000, source="apipay",
                             external_id="invoice:1")
    await repo.add_operation(type="expense", amount=-10_000_000, category="Закуп",
                             created_by=1)

    summary = await build_day_summary(repo, today_local(settings.timezone))

    assert summary.opening + summary.income + summary.expenses == summary.balance
    assert summary.balance == 109_000_000     # 1 090 000 ₸ — как в образце ТЗ


async def test_later_days_exclude_the_start_balance_from_opening_twice(repo):
    """На следующий день стартовая сумма уже внутри balance_before, не задваивается."""
    await repo.add_operation(
        type="start", amount=100_000_000, comment="Стартовый баланс", created_by=1,
        occurred_at=datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc),
    )
    await repo.add_operation(
        type="income", amount=5_000_000, source="apipay", external_id="invoice:7",
        occurred_at=datetime(2026, 10, 13, 6, 0, tzinfo=timezone.utc),
    )

    summary = await build_day_summary(repo, "2026-10-13")

    assert summary.opening == 100_000_000
    assert summary.income == 5_000_000
    assert summary.opening + summary.income == summary.balance == 105_000_000
