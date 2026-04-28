"""Per-cell module weight recalibration from validation history.

For each (risk_profile × timeframe) cell, look at all validated suggestions
that landed in that cell. For each module, compute Pearson correlation
between (module.score × module.confidence) and the realized outcome_score.
Modules with positive correlation get UP-weighted; modules with negative
or zero correlation get DOWN-weighted toward their prior (default).

We never zero out a module — the minimum is 25% of its default weight, the
maximum is 200%. This keeps recalibration from collapsing onto a single
"winning" module on a small sample.

The recalibrated weights are stored as a JSONL line in
data_repo/models/weights_history.jsonl (Phase 6 publishes; for now we
write to a local file the same shape).

Trigger: only run when we have ≥30 validations for the cell. Below that,
the noise is too high.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Suggestion, SuggestionValidation
from app.synthesis.weights import RISK_PROFILES, TIMEFRAMES, cell_weights

log = logging.getLogger(__name__)

MIN_VALIDATIONS_PER_CELL = 30
WEIGHT_FLOOR = 0.25   # 25% of default
WEIGHT_CEIL = 2.00    # 200% of default


@dataclass
class CellRecalibration:
    risk: str
    timeframe: str
    n_samples: int
    weights: dict[str, float]
    correlations: dict[str, float]


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------
def recalibrate_cell_weights(db: Session) -> list[CellRecalibration]:
    """Recalibrate every (risk × timeframe) cell with enough samples.

    Returns the list of cells that were updated. Writes a JSONL line per
    update to <data_repo>/models/weights_history.jsonl (Phase 6 publishes).
    """
    out: list[CellRecalibration] = []
    s = get_settings()
    history_path = s.data_repo_dir / "models" / "weights_history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for risk in RISK_PROFILES:
        for tf in TIMEFRAMES:
            cell = _recalibrate_one_cell(db, risk, tf)
            if cell is None:
                continue
            out.append(cell)

            line = {
                "schema_version": "0.1",
                "ts": timestamp,
                "trigger": "scheduled_recalibration",
                "cell": f"{cell.risk}.{cell.timeframe}",
                "n_samples": cell.n_samples,
                "weights": cell.weights,
                "correlations": cell.correlations,
            }
            with history_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, default=str) + "\n")

    log.info("recalibration: %d cells updated", len(out))
    return out


def _recalibrate_one_cell(db: Session, risk: str, timeframe: str) -> CellRecalibration | None:
    """Recompute weights for a single (risk × timeframe) cell."""
    rows = db.execute(
        select(Suggestion, SuggestionValidation)
        .join(SuggestionValidation, SuggestionValidation.suggestion_id == Suggestion.id)
        .where(and_(
            Suggestion.risk_profile == risk,
            Suggestion.timeframe == timeframe,
        ))
    ).all()
    if len(rows) < MIN_VALIDATIONS_PER_CELL:
        return None

    # Collect outcomes and per-module signed scores from the saved rationale
    outcomes: list[float] = []
    module_signals: dict[str, list[float]] = {}
    for sug, val in rows:
        outcomes.append(float(val.outcome_score))
        rationale = sug.rationale or {}
        # We didn't persist the raw module scores on the Suggestion row
        # explicitly — but the contributors list inside `confidence_drivers`
        # carries (module, weighted_contrib). Use that as the signal.
        for cd in (rationale.get("confidence_drivers") or []):
            mod = cd.get("factor")
            delta = cd.get("delta")
            if mod is None or delta is None:
                continue
            module_signals.setdefault(mod, []).append(float(delta))

    if not outcomes or not module_signals:
        return None

    # Compute Pearson r per module (on overlapping length only)
    correlations: dict[str, float] = {}
    for mod, signals in module_signals.items():
        n = min(len(signals), len(outcomes))
        if n < 10:
            continue
        r = _pearson(signals[:n], outcomes[:n])
        if r is not None:
            correlations[mod] = r

    if not correlations:
        return None

    # Translate correlations to weight scales
    defaults = cell_weights(risk)
    new_weights = dict(defaults)
    for mod, r in correlations.items():
        # r in [-1, 1] → scale in [WEIGHT_FLOOR, WEIGHT_CEIL] linearly
        scale = max(WEIGHT_FLOOR, min(WEIGHT_CEIL, 1.0 + r))
        new_weights[mod] = round(defaults.get(mod, 0.0) * scale, 4)

    # Renormalize to sum to 1.0 (keeps cell scoring stable)
    total = sum(new_weights.values()) or 1.0
    new_weights = {k: round(v / total, 4) for k, v in new_weights.items()}

    return CellRecalibration(
        risk=risk,
        timeframe=timeframe,
        n_samples=len(outcomes),
        weights=new_weights,
        correlations={k: round(v, 4) for k, v in correlations.items()},
    )


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n != len(ys) or n == 0:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs)
    dy = sum((y - my) ** 2 for y in ys)
    if dx == 0 or dy == 0:
        return None
    return num / (dx ** 0.5 * dy ** 0.5)
