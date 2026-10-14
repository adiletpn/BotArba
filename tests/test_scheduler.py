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
    scheduler = create_scheduler(bot=None, db=None, repo=repo, settings=settings)

    fields = _fields(scheduler, "evening_summary")
    assert fields["hour"] == "21"
    assert fields["minute"] == "0"
    assert str(_job(scheduler, "evening_summary").trigger.timezone) == "Asia/Almaty"


async def test_summary_time_is_configurable(repo, settings):
    from dataclasses import replace

    moved = replace(settings, summary_hour=18, summary_minute=30)
    scheduler = create_scheduler(bot=None, db=None, repo=repo, settings=moved)

    fields = _fields(scheduler, "evening_summary")
    assert (fields["hour"], fields["minute"]) == ("18", "30")


async def test_sync_and_backup_jobs_exist(repo, settings):
    scheduler = create_scheduler(bot=None, db=None, repo=repo, settings=settings)

    assert _fields(scheduler, "hourly_sync")["minute"] == "5", "сверка — каждый час в :05"

    backup = _fields(scheduler, "daily_backup")
    assert (backup["hour"], backup["minute"]) == ("3", "30")
