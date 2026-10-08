"""Validation sweep orchestrator — runs as part of the morning pipeline.

Order:
  1. Run the validation sweep (find due suggestions, score them).
  2. Re-fit confidence calibration model from the now-larger sample.
  3. Recalibrate per-cell module weights for cells with enough history.

Phase 4 — fully implemented. Phase 6 will additionally write the per-day
results.json + aggregate_performance.json into the data repo.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import RunLog
from app.services.data_publisher import publish
from app.validation.calibration import maybe_recalibrate
from app.validation.recalibration import recalibrate_cell_weights
from app.validation.sweep import sweep_due_validations
from app.redact import redact_exc

log = logging.getLogger(__name__)


async def run_validation_sweep() -> None:
    started = datetime.now(timezone.utc)
    log.info("Validation sweep starting")
    db = SessionLocal()
    run = None
    try:
        run = RunLog(
            run_type="validation_sweep",
            status="running",
            started_at=started,
            summary={"phase": "4-validation"},
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        # 1. Score due suggestions
        # Worker threads keep the API/UI responsive during the sweep.
        sweep_summary = await asyncio.to_thread(sweep_due_validations, db)

        # 2. Calibration (only kicks in at >= MIN_VALIDATIONS_FOR_CALIBRATION)
        calibration_model = await asyncio.to_thread(maybe_recalibrate, db)

        # 3. Per-cell weight recalibration
        recalibrations = await asyncio.to_thread(recalibrate_cell_weights, db)

        run.status = "ok" if sweep_summary.errors == {} else "partial"
        run.finished_at = datetime.now(timezone.utc)
        run.summary = {
            "phase": "4-validation",
            "validation_sweep": {
                "candidates": sweep_summary.candidates,
                "validated": sweep_summary.validated,
                "skipped": sweep_summary.skipped,
                "new_validation_ids": sweep_summary.new_validations,
            },
            "calibration": {
                "fitted": calibration_model is not None,
                "n_samples": calibration_model.n_samples if calibration_model else 0,
                "n_breakpoints": (
                    len(calibration_model.breakpoints) if calibration_model else 0
                ),
            },
            "recalibration": {
                "cells_updated": len(recalibrations),
                "cells": [f"{r.risk}.{r.timeframe}" for r in recalibrations],
            },
        }
        run.errors = sweep_summary.errors or None
        db.commit()
        log.info(
            "Validation sweep finished — %d validated, calibrate=%s, recal=%d cells",
            sweep_summary.validated,
            "yes" if calibration_model else "no",
            len(recalibrations),
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Validation sweep failed: %s", exc)
        if run is not None:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.errors = {"sweep": redact_exc(exc, 300)}
            db.commit()
    finally:
        db.close()
        await asyncio.to_thread(publish, "validation_sweep")
