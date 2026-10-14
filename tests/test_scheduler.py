"""Критерий приёмки: вечерняя сводка приходит в 21:00 по Алматы сама."""

from app.scheduler import create_scheduler


def _fields(scheduler, job_id: str) -> dict[str, str]:
    """Поля cron-триггера задания в виде {'hour': '21', ...}.

    Планировщик в тестах не запускается: проверяется расписание, а не
    исполнение. Поэтому и shutdown() не вызывается — у незапущенного
    AsyncIOScheduler нет привязанного цикла событий.
    """
    return {f.name: str(f) for f in _job(scheduler, job_id).trigger.fields}


def _job(scheduler, job_id: str):
    job = scheduler.get_job(job_id)
    assert job is not None, f"задание {job_id} не зарегистрировано"
    return job


async def test_summary_job_runs_at_21_00_almaty(repo, settings):
    scheduler = await create_scheduler(bot=None, db=None, repo=repo, settings=settings)

    fields = _fields(scheduler, "evening_summary")
    assert fields["hour"] == "21"
    assert fields["minute"] == "0"
    assert str(_job(scheduler, "evening_summary").trigger.timezone) == "Asia/Almaty"


async def test_summary_time_falls_back_to_the_environment(repo, settings):
    """Пока в настройках ничего нет, время берётся из .env."""
    from dataclasses import replace

    moved = replace(settings, summary_hour=18, summary_minute=30)
    scheduler = await create_scheduler(bot=None, db=None, repo=repo, settings=moved)

    fields = _fields(scheduler, "evening_summary")
    assert (fields["hour"], fields["minute"]) == ("18", "30")


async def test_sync_and_backup_jobs_exist(repo, settings):
    scheduler = await create_scheduler(bot=None, db=None, repo=repo, settings=settings)

    assert _fields(scheduler, "hourly_sync")["minute"] == "5", "сверка — каждый час в :05"

    backup = _fields(scheduler, "daily_backup")
    assert (backup["hour"], backup["minute"]) == ("3", "30")


async def test_settings_table_wins_over_the_environment(repo, settings):
    """ТЗ: время сводки меняется в настройках, а не редеплоем."""
    await repo.seed_settings("21:00", "Asia/Almaty")
    await repo.set_summary_time(19, 45)

    scheduler = await create_scheduler(bot=None, db=None, repo=repo, settings=settings)

    fields = _fields(scheduler, "evening_summary")
    assert (fields["hour"], fields["minute"]) == ("19", "45")


async def test_seed_settings_does_not_overwrite_a_changed_time(repo):
    """Перезапуск не должен возвращать время из .env поверх настроенного."""
    await repo.seed_settings("21:00", "Asia/Almaty")
    await repo.set_summary_time(19, 45)

    # Имитация следующего старта процесса с прежним .env
    await repo.seed_settings("21:00", "Asia/Almaty")

    assert await repo.get_summary_time((21, 0)) == (19, 45)


async def test_broken_summary_time_falls_back_instead_of_crashing(repo):
    await repo.set_setting(repo.SUMMARY_TIME_KEY, "четверть девятого")
    assert await repo.get_summary_time((21, 0)) == (21, 0)

    await repo.set_setting(repo.SUMMARY_TIME_KEY, "25:99")
    assert await repo.get_summary_time((21, 0)) == (21, 0)


async def test_rescheduling_moves_the_live_job(repo, settings):
    from app.scheduler import reschedule_summary

    scheduler = await create_scheduler(bot=None, db=None, repo=repo, settings=settings)
    assert _fields(scheduler, "evening_summary")["hour"] == "21"

    reschedule_summary(scheduler, 7, 15)

    fields = _fields(scheduler, "evening_summary")
    assert (fields["hour"], fields["minute"]) == ("7", "15")


async def test_sync_interval_is_configurable(repo, settings):
    """Когда вебхук недоступен, частота опроса — единственный рычаг скорости."""
    from dataclasses import replace

    scheduler = await create_scheduler(
        bot=None, db=None, repo=repo, settings=replace(settings, sync_every_minutes=5)
    )
    assert _fields(scheduler, "hourly_sync")["minute"] == "*/5"


async def test_sync_interval_is_clamped_to_an_hour(repo, settings):
    from dataclasses import replace

    scheduler = await create_scheduler(
        bot=None, db=None, repo=repo, settings=replace(settings, sync_every_minutes=999)
    )
    # Больше часа крон по минутам не выражает — откатываемся к разу в час
    assert _fields(scheduler, "hourly_sync")["minute"] == "5"
