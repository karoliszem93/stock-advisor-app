"""Confidence calibration — maps stated confidence to realized hit rate.

Until we have enough validated suggestions, the raw confidence emitted
by synthesis is uncalibrated. After ≥50 validations exist, we fit an
isotonic regression that maps raw confidence → realized hit rate, and
store the result so the UI can display BOTH numbers.

We avoid sklearn here to keep deps minimal — implementing a simple
piecewise-constant isotonic via the pool-adjacent-violators algorithm
in pure Python.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Suggestion, SuggestionValidation

log = logging.getLogger(__name__)

MIN_VALIDATIONS_FOR_CALIBRATION = 50


@dataclass
class CalibrationModel:
    """Piecewise-constant mapping from raw_conf → realized hit rate.

    Stored as a sorted list of breakpoints with the calibrated value
    between consecutive breakpoints.
    """
    breakpoints: list[float]   # sorted; raw confidence thresholds
    values: list[float]        # same length; realized hit rate above the breakpoint
    n_samples: int = 0
    fit_at: str | None = None

    def calibrate(self, raw_confidence: float) -> float:
        """Apply the mapping. Returns calibrated confidence in [0, 1]."""
        if not self.breakpoints:
            return raw_confidence
        # Find the largest breakpoint <= raw_confidence
        v = self.values[0]
        for bp, val in zip(self.breakpoints, self.values):
            if raw_confidence >= bp:
                v = val
            else:
                break
        return max(0.0, min(1.0, v))


# ---------------------------------------------------------------------------
# PAVA — pool-adjacent-violators algorithm for isotonic regression.
# ---------------------------------------------------------------------------
def _pava(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    """Return (breakpoints, values) — non-decreasing fit of ys vs xs.

    xs must be sorted ascending. Standard pool-adjacent-violators.
    """
    n = len(xs)
    if n == 0:
        return [], []

    blocks: list[dict] = [{"x": xs[i], "y": ys[i], "w": 1.0} for i in range(n)]

    i = 0
    while i + 1 < len(blocks):
        if blocks[i]["y"] <= blocks[i + 1]["y"]:
            i += 1
            continue
        # Merge blocks i and i+1
        a, b = blocks[i], blocks[i + 1]
        merged = {
            "x": a["x"],
            "y": (a["y"] * a["w"] + b["y"] * b["w"]) / (a["w"] + b["w"]),
            "w": a["w"] + b["w"],
        }
        blocks = blocks[:i] + [merged] + blocks[i + 2:]
        if i > 0:
            i -= 1

    return [b["x"] for b in blocks], [b["y"] for b in blocks]


# ---------------------------------------------------------------------------
# Fit from DB
# ---------------------------------------------------------------------------
def fit_calibration(db: Session) -> CalibrationModel | None:
    """Build a calibration model from validated suggestions in the DB.

    Returns None if we don't have enough samples yet.
    """
    rows = db.execute(
        select(Suggestion.confidence, SuggestionValidation.outcome)
        .join(SuggestionValidation, SuggestionValidation.suggestion_id == Suggestion.id)
    ).all()

    if len(rows) < MIN_VALIDATIONS_FOR_CALIBRATION:
        log.info("calibration: only %d validations (<%d needed) — skipping fit",
                 len(rows), MIN_VALIDATIONS_FOR_CALIBRATION)
        return None

    pairs = [(float(c), 1.0 if outcome == "correct" else 0.0)
             for c, outcome in rows if c is not None and outcome is not None]
    if not pairs:
        return None

    pairs.sort(key=lambda p: p[0])
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]

    bps, vals = _pava(xs, ys)
    from datetime import datetime, timezone
    return CalibrationModel(
        breakpoints=bps,
        values=vals,
        n_samples=len(pairs),
        fit_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------------------------
# Apply to existing suggestions
# ---------------------------------------------------------------------------
def apply_calibration(db: Session, model: CalibrationModel) -> int:
    """Update all Suggestion rows' confidence_calibrated using the new model.

    Returns the number of rows updated.
    """
    rows = db.scalars(select(Suggestion)).all()
    for r in rows:
        if r.confidence is not None:
            r.confidence_calibrated = round(model.calibrate(float(r.confidence)), 4)
    db.commit()
    return len(rows)


def maybe_recalibrate(db: Session) -> CalibrationModel | None:
    """Convenience: fit + apply in one call. Returns the model if fit happened."""
    model = fit_calibration(db)
    if model is not None:
        apply_calibration(db, model)
        log.info("calibration: applied with %d samples, %d breakpoints",
                 model.n_samples, len(model.breakpoints))
    return model
