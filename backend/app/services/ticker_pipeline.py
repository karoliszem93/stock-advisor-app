"""Single-ticker pipeline.

Same pipeline as the daily run, but restricted to one ticker. Used by the
"Run analysis" button on the Watchlist page for fast triage of individual
names without burning the full 5-minute / ~30-LLM-call run.

Runtime: ~10–20s on Gemini Flash-Lite (1 LLM call, full 13-module analysis).
Existing suggestions for (ticker, today) are deleted before the run so
results don't accumulate as duplicates on re-run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.db import SessionLocal
from app.models import RunLog
from app.services.universe import UniverseEntry
from app.synthesis.orchestrator import generate_suggestions

log = logging.getLogger(__name__)


async def run_ticker_pipeline(ticker: str) -> None:
    s = get_settings()
    started = datetime.now(timezone.utc)
    snapshot_date = datetime.now(ZoneInfo(s.timezone)).date()
    ticker_u = ticker.strip().upper()
    log.info("Ticker pipeline starting (ticker=%s)", ticker_u)

    db = SessionLocal()
    run = None
    try:
        run = RunLog(
            run_type="ticker_pipeline",
            status="running",
            started_at=started,
            ollama_model=s.ollama_model,
            summary={
                "phase": "single-ticker",
                "ticker": ticker_u,
                "snapshot_date": snapshot_date.isoformat(),
            },
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        # Build a one-entry universe. asset_type defaults to "equity";
        # build_ticker_context auto-detects ETFs from yfinance get_info.
        universe = [
            UniverseEntry(
                ticker=ticker_u,
                asset_type="equity",
                source="manual_run",
            )
        ]

        summary = generate_suggestions(
            snapshot_date,
            db,
            universe=universe,
            delete_existing_for_tickers=[ticker_u],
        )

        run.status = "ok" if summary.suggestions_created else "partial"
        run.finished_at = datetime.now(timezone.utc)
        run.summary = {
            "phase": "single-ticker",
            "ticker": ticker_u,
            "snapshot_date": snapshot_date.isoformat(),
            "tickers_analyzed": summary.tickers_analyzed,
            "suggestions_created": summary.suggestions_created,
            "cells": summary.cells,
            "llm_calls": summary.llm_calls,
            "llm_fallbacks": summary.fallbacks,
            "duration_seconds": summary.duration_seconds,
        }
        run.errors = summary.errors or None
        db.commit()
        log.info(
            "Ticker pipeline finished — %s: %d suggestions in %ss",
            ticker_u, summary.suggestions_created, summary.duration_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Ticker pipeline failed for %s: %s", ticker_u, exc)
        if run is not None:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.errors = {"pipeline": repr(exc)[:300]}
            db.commit()
    finally:
        db.close()
