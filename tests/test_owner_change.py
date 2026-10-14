"""Смена владельца: разработчик ставит бота, потом доступ переходит к ИП."""

from tests.conftest import OWNER_ID

DEVELOPER_ID = 6_522_166_956
REAL_OWNER_ID = 111_222_333


async def test_changing_the_whitelist_revokes_the_previous_owner(repo):
    # Этап 1: бота ставит разработчик, доступ только у него.
    await repo.ensure_owners((DEVELOPER_ID,))
    assert await repo.is_allowed(DEVELOPER_ID) is True
    assert await repo.is_allowed(REAL_OWNER_ID) is False

    # Разработчик успел внести операцию — она не должна пострадать.
    await repo.add_operation(
        type="expense", amount=-5_000, category="Прочее", created_by=DEVELOPER_ID
    )

    # Этап 2: OWNER_TELEGRAM_IDS меняют на настоящего владельца.
    await repo.ensure_owners((REAL_OWNER_ID,))

    assert await repo.is_allowed(REAL_OWNER_ID) is True
    assert await repo.is_allowed(DEVELOPER_ID) is False, "прежний доступ должен отзываться"

    # Сводка уходит только действующему владельцу.
    assert await repo.owner_ids() == [REAL_OWNER_ID]

    # История при этом целая: строки пользователей не удаляются.
    assert await repo.balance() == -5_000
    assert len(await repo.recent_operations(10)) == 1


async def test_both_can_be_listed_at_once(repo):
    """Передача дел: какое-то время нужны оба."""
    await repo.ensure_owners((DEVELOPER_ID, REAL_OWNER_ID))

    assert await repo.is_allowed(DEVELOPER_ID) is True
    assert await repo.is_allowed(REAL_OWNER_ID) is True
    assert await repo.owner_ids() == sorted([DEVELOPER_ID, REAL_OWNER_ID])


async def test_returning_a_revoked_user_restores_access(repo):
    await repo.ensure_owners((DEVELOPER_ID,))
    await repo.ensure_owners((REAL_OWNER_ID,))
    assert await repo.is_allowed(DEVELOPER_ID) is False

    await repo.ensure_owners((DEVELOPER_ID, REAL_OWNER_ID))
    assert await repo.is_allowed(DEVELOPER_ID) is True


async def test_fixture_owner_is_revoked_when_not_listed(repo):
    """Страховка: фикстура заводит OWNER_ID, и он тоже подчиняется списку."""
    assert await repo.is_allowed(OWNER_ID) is True
    await repo.ensure_owners((DEVELOPER_ID,))
    assert await repo.is_allowed(OWNER_ID) is False
