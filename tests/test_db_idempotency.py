async def test_repeated_webhook_does_not_double_the_amount(repo):
    """Критерий приёмки: повторная отправка того же вебхука не удваивает сумму."""
    first = await repo.add_operation(
        type="income", amount=19_000_000, source="apipay", external_id="invoice:42"
    )
    second = await repo.add_operation(
        type="income", amount=19_000_000, source="apipay", external_id="invoice:42"
    )

    assert first is not None
    assert second is None, "повторный вебхук должен быть распознан как дубликат"
    assert await repo.balance() == 19_000_000


async def test_different_invoices_are_both_recorded(repo):
    await repo.add_operation(type="income", amount=1_000, source="apipay",
                             external_id="invoice:1")
    await repo.add_operation(type="income", amount=1_000, source="apipay",
                             external_id="invoice:2")
    assert await repo.balance() == 2_000


async def test_manual_operations_do_not_collide_on_null_external_id(repo):
    """Ручные расходы идут без external_id и не должны мешать друг другу."""
    for _ in range(3):
        assert await repo.add_operation(type="expense", amount=-1_000,
                                        category="Прочее") is not None
    assert await repo.balance() == -3_000
