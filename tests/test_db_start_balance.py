async def test_start_balance_is_set_only_once(repo):
    """Критерий приёмки: повторно стартовая сумма не меняется без /correct."""
    assert await repo.has_start_balance() is False

    first = await repo.set_start_balance(100_000_000, created_by=1)
    assert first is not None
    assert await repo.has_start_balance() is True

    second = await repo.set_start_balance(500_000_000, created_by=1)
    assert second is None, "вторая стартовая сумма не должна записываться"
    assert await repo.balance() == 100_000_000


async def test_correction_can_still_adjust_the_balance(repo):
    await repo.set_start_balance(100_000_000, created_by=1)
    await repo.add_operation(
        type="correction", amount=50_000_000, comment="Наличные мимо ApiPay",
        created_by=1,
    )
    assert await repo.balance() == 150_000_000
