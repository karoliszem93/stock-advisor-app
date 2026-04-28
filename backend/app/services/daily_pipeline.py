"""Daily analysis & suggestion pipeline.

Wired through Phase 3:
  - resolve universe (watchlist + curated ETFs)
  - snapshot every ticker (yfinance + FMP + Finnhub + EDGAR + FRED + ...)
  - run all 13 analysis modules per ticker
  - score per (risk × timeframe) cell, pick top candidates
  - generate base thesis via Ollama (one per unique ticker)
  - persist Suggestion rows to SQLite

Pending Phase 6: pushing the daily snapshots/suggestions/analysis JSON
files into the stock-advisor-data repo. For now everything lives in the
local SQLite DB and can be inspected via the API or the frontend.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.db import SessionLocal
from app.models import RunLog
from app.synthesis.orchestrator import generate_suggestions

log = logging.getLogger(__name__)


async def run_daily_pipeline() -> None:
    s = get_settings()
    started = datetime.now(timezone.utc)
    snapshot_date = datetime.now(ZoneInfo(s.timezone)).date()
    log.info(
        "Daily pipeline starting (snapshot=%s, model=%s)",
        snapshot_date.isoformat(), s.ollama_model,
    )

    db = SessionLocal()
    run = None
    try:
        run = RunLog(
            run_type="daily_pipeline",
            status="running",
            started_at=started,
            ollama_model=s.ollama_model,
            summary={"phase": "3-synthesis", "snapshot_date": snapshot_date.isoformat()},
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        summary = generate_suggestions(snapshot_date, db)

        run.status = "ok" if summary.suggestions_created else "partial"
        run.finished_at = datetime.now(timezone.utc)
        run.summary = {
            "phase": "3-synthesis",
            "snapshot_date": snapshot_date.isoformat(),
            "universe_size": summary.universe_size,
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
            "Daily pipeline finished — %d suggestions in %ss",
            summary.suggestions_created, summary.duration_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Daily pipeline failed: %s", exc)
        if run is not None:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.errors = {"pipeline": repr(exc)[:300]}
            db.commit()
    finally:
        db.close()
