"""Manual pipeline triggers — useful for debugging without waiting for the schedule."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from app.services.daily_pipeline import run_daily_pipeline
from app.services.validation_pipeline import run_validation_sweep

router = APIRouter()
log = logging.getLogger(__name__)


@router.post("/daily")
async def trigger_daily() -> dict:
    """Kick off the daily analysis + suggestion pipeline now (async, returns immediately)."""
    log.info("Manual trigger: daily_pipeline")
    asyncio.create_task(run_daily_pipeline())
    return {"triggered": "daily_pipeline"}


@router.post("/validate")
async def trigger_validation() -> dict:
    """Kick off the validation sweep now."""
    log.info("Manual trigger: validation_sweep")
    asyncio.create_task(run_validation_sweep())
    return {"triggered": "validation_sweep"}
