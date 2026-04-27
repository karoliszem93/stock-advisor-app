"""Daily analysis & suggestion pipeline.

Phase 0: skeleton — logs that it ran, writes a RunLog row, and stops.
Later phases fill this in:
  Phase 1: pull data from providers
  Phase 2: run analysis modules
  Phase 3: synthesize suggestions via Ollama
  Phase 6: commit results to data repo
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.config import get_settings
from app.db import SessionLocal
from app.models import RunLog

log = logging.getLogger(__name__)


async def run_daily_pipeline() -> None:
    s = get_settings()
    started = datetime.now(timezone.utc)
    log.info("Daily pipeline starting (env=%s, model=%s)", s.app_env, s.ollama_model)

    db = SessionLocal()
    try:
        run = RunLog(
            run_type="daily_pipeline",
            status="running",
            started_at=started,
            ollama_model=s.ollama_model,
            summary={"phase": "0-skeleton"},
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        # ---- Phase 1+: real work goes here ----
        # 1. Resolve universe (watchlist + curated ETFs)
        # 2. Snapshot data from providers
        # 3. Run analysis modules per ticker
        # 4. Synthesize suggestions via Ollama
        # 5. Persist Suggestions, write JSON files in data repo
        # 6. git commit + push the data repo
        # 7. Trigger native macOS notification

        run.status = "ok"
        run.finished_at = datetime.now(timezone.utc)
        run.summary = {"phase": "0-skeleton", "note": "no-op until Phase 1 ships"}
        db.commit()
        log.info("Daily pipeline finished (skeleton no-op)")
    except Exception as exc:  # noqa: BLE001
        log.exception("Daily pipeline failed: %s", exc)
        if run is not None:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.errors = {"pipeline": repr(exc)}
            db.commit()
    finally:
        db.close()
