"""APScheduler wrapper that makes sure the daily runs happen once per weekday.

Instead of a single 08:00 cron trigger (which is silently skipped when the
machine is off or asleep at that moment), a catch-up check runs shortly
after startup and then every CHECK_INTERVAL_MINUTES. On weekdays, once the
scheduled time (08:00 Europe/Vilnius by default) has passed, it starts
whatever hasn't completed yet today, in order:

  1. validation sweep  (cheap; scores already-stored suggestions)
  2. daily pipeline    (heavier analysis + suggestion generation)

So the runs happen at 08:00 if the machine is on, or as soon as it boots /
wakes up afterwards. Failed runs are retried on later checks, up to
MAX_ATTEMPTS_PER_DAY per run type.

DST is handled by doing all wall-clock math in the configured timezone.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import get_settings

log = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None

CHECK_INTERVAL_MINUTES = 15
STARTUP_DELAY_SECONDS = 60
MAX_ATTEMPTS_PER_DAY = 3


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        s = get_settings()
        _scheduler = AsyncIOScheduler(timezone=ZoneInfo(s.timezone))
    return _scheduler


def _today_runs(run_type: str, day_start_utc: datetime) -> list:
    from app.db import SessionLocal
    from app.models import RunLog

    db = SessionLocal()
    try:
        # started_at is stored as naive UTC in SQLite
        return list(db.scalars(
            select(RunLog).where(
                RunLog.run_type == run_type,
                RunLog.started_at >= day_start_utc.replace(tzinfo=None),
            )
        ).all())
    finally:
        db.close()


async def ensure_daily_runs() -> None:
    """Start today's validation sweep / daily pipeline if they haven't completed yet."""
    from app.services.daily_pipeline import run_daily_pipeline
    from app.services.validation_pipeline import run_validation_sweep

    s = get_settings()
    tz = ZoneInfo(s.timezone)
    now = datetime.now(tz)
    if now.weekday() >= 5:  # Sat/Sun — markets closed, nothing new to analyze
        return
    if now.time() < time(s.schedule_hour, s.schedule_minute):
        return

    day_start_utc = datetime.combine(now.date(), time.min, tz).astimezone(timezone.utc)

    for run_type, fn in (
        ("validation_sweep", run_validation_sweep),
        ("daily_pipeline", run_daily_pipeline),
    ):
        runs = _today_runs(run_type, day_start_utc)
        statuses = {r.status for r in runs}
        if "running" in statuses:
            log.info("Catch-up: %s already running — will check again later", run_type)
            return
        if statuses & {"ok", "partial"}:
            continue
        if len(runs) >= MAX_ATTEMPTS_PER_DAY:
            log.warning("Catch-up: %s failed %d times today — giving up until tomorrow",
                        run_type, len(runs))
            continue
        log.info("Catch-up: starting %s for %s (attempt %d)",
                 run_type, now.date().isoformat(), len(runs) + 1)
        await fn()


def start_scheduler() -> None:
    """Register jobs and start the scheduler. Idempotent."""
    s = get_settings()
    scheduler = get_scheduler()

    if scheduler.running:
        return

    scheduler.add_job(
        ensure_daily_runs,
        trigger=IntervalTrigger(minutes=CHECK_INTERVAL_MINUTES, timezone=ZoneInfo(s.timezone)),
        next_run_time=datetime.now(ZoneInfo(s.timezone)) + timedelta(seconds=STARTUP_DELAY_SECONDS),
        id="ensure_daily_runs",
        name="Daily validation sweep + analysis pipeline (with catch-up)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )

    scheduler.start()
    log.info(
        "Scheduler started — daily runs from %02d:%02d %s (Mon-Fri), "
        "checked at startup and every %d min",
        s.schedule_hour, s.schedule_minute, s.timezone, CHECK_INTERVAL_MINUTES,
    )


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Scheduler shut down.")
