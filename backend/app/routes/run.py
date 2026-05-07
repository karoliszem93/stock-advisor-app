"""Manual pipeline triggers — useful for debugging without waiting for the schedule."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from app.services.daily_pipeline import run_daily_pipeline
from app.services.ticker_pipeline import run_ticker_pipeline
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


@router.post("/ticker/{ticker}")
async def trigger_ticker(ticker: str) -> dict:
    """Kick off a fast single-ticker analysis (~10–20s, 1 LLM call)."""
    t = ticker.strip().upper()
    if not t:
        return {"error": "empty ticker"}
    log.info("Manual trigger: ticker_pipeline for %s", t)
    asyncio.create_task(run_ticker_pipeline(t))
    return {"triggered": "ticker_pipeline", "ticker": t}
