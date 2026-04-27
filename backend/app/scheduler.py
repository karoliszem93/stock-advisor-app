"""APScheduler wrapper that triggers the daily pipeline at 08:00 Europe/Vilnius
on weekdays (Mon-Fri).

DST is handled automatically by passing the timezone string to CronTrigger.
"""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings

log = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        s = get_settings()
        _scheduler = AsyncIOScheduler(timezone=ZoneInfo(s.timezone))
    return _scheduler


def start_scheduler() -> None:
    """Register jobs and start the scheduler. Idempotent."""
    from app.services.daily_pipeline import run_daily_pipeline
    from app.services.validation_pipeline import run_validation_sweep

    s = get_settings()
    scheduler = get_scheduler()

    if scheduler.running:
        return

    # Validation sweep runs first (cheap; uses already-stored suggestions),
    # then the heavier daily analysis pipeline.
    scheduler.add_job(
        run_validation_sweep,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=s.schedule_hour,
            minute=s.schedule_minute,
            timezone=ZoneInfo(s.timezone),
        ),
        id="validation_sweep",
        name="Daily validation sweep",
        replace_existing=True,
        misfire_grace_time=60 * 30,  # 30 minutes
    )

    scheduler.add_job(
        run_daily_pipeline,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=s.schedule_hour,
            minute=s.schedule_minute + 5,  # 5 minutes after validation
            timezone=ZoneInfo(s.timezone),
        ),
        id="daily_pipeline",
        name="Daily analysis & suggestion pipeline",
        replace_existing=True,
        misfire_grace_time=60 * 60 * 2,  # 2 hours
    )

    scheduler.start()
    log.info(
        "Scheduler started — daily run at %02d:%02d %s (Mon-Fri)",
        s.schedule_hour, s.schedule_minute, s.timezone,
    )


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Scheduler shut down.")
