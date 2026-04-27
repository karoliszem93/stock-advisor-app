"""Validation sweep — grade suggestions whose target_date has arrived.

Phase 0: skeleton.
Phase 4: actual outcome computation, EUR-denominated returns split into
price/dividend/FX/tax components, calibration update, weight recalibration.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import RunLog

log = logging.getLogger(__name__)


async def run_validation_sweep() -> None:
    started = datetime.now(timezone.utc)
    log.info("Validation sweep starting")
    db = SessionLocal()
    try:
        run = RunLog(
            run_type="validation_sweep",
            status="running",
            started_at=started,
            summary={"phase": "0-skeleton"},
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        # ---- Phase 4+: real work goes here ----
        # 1. SELECT suggestions WHERE target_date <= today AND no validation row yet
        # 2. For each: fetch actual price action over the window
        # 3. Compute returns breakdown (price, dividends, FX, tax)
        # 4. Insert SuggestionValidation
        # 5. Update calibration model (after >=50 validations)
        # 6. Update module weights per (risk, timeframe) cell
        # 7. Append to data repo: validations/<date>/results.json

        run.status = "ok"
        run.finished_at = datetime.now(timezone.utc)
        run.summary = {"phase": "0-skeleton", "note": "no-op until Phase 4 ships"}
        db.commit()
        log.info("Validation sweep finished (skeleton no-op)")
    except Exception as exc:  # noqa: BLE001
        log.exception("Validation sweep failed: %s", exc)
        if run is not None:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.errors = {"sweep": repr(exc)}
            db.commit()
    finally:
        db.close()
