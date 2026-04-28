"""Per-cell candidate scoring + ranking.

For each (risk_profile × timeframe) cell:
  1. Filter out tickers that fail risk-profile hard filters.
  2. Compute a weighted cell_score for each remaining ticker:
        cell_score = Σ_m  (cell_w[m] * mod.horizon_w[tf] * mod.score * mod.confidence)
                     -------------------------------------------------------------------
                          Σ_m  (cell_w[m] * mod.horizon_w[tf] * mod.confidence)
     where m runs over modules with non-null score.
  3. Apply event_awareness penalty if earnings fall inside the window.
  4. Compute cell_confidence as a coverage-weighted average of module confidence.
  5. Rank candidates by |cell_score| × confidence (signal strength).
  6. Classify direction by cell_score sign vs threshold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from app.analysis.base import ModuleResult
from app.synthesis.weights import cell_weights, filter_for_profile

# Above this absolute score, we issue a Buy / Sell-short. Below, "Avoid".
DIRECTION_THRESHOLD = 0.12

# Minimum cell confidence below which we never issue a Buy / Sell-short.
MIN_CONFIDENCE = 0.30


@dataclass
class Candidate:
    """A single (ticker × risk × timeframe) scoring result, pre-thesis."""

    ticker: str
    asset_type: str
    risk_profile: str
    timeframe: str
    cell_score: float
    cell_confidence: float
    direction: str            # "buy" | "avoid" | "sell_short"
    contributors: list[dict] = field(default_factory=list)
    # Top contributing modules: [{"module":"technical","weighted_score":+0.18},...]
    filter_passed: bool = True
    filter_reason: str | None = None
    notes: list[str] = field(default_factory=list)
    raw_module_scores: dict = field(default_factory=dict)
    # raw_module_scores: {module_name: {"score","confidence","direction","horizon_w"}}

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "asset_type": self.asset_type,
            "risk_profile": self.risk_profile,
            "timeframe": self.timeframe,
            "cell_score": self.cell_score,
            "cell_confidence": self.cell_confidence,
            "direction": self.direction,
            "contributors": self.contributors,
            "filter_passed": self.filter_passed,
            "filter_reason": self.filter_reason,
            "notes": self.notes,
        }


def score_candidate(
    ticker: str,
    asset_type: str,
    risk_profile: str,
    timeframe: str,
    module_results: dict[str, ModuleResult],
) -> Candidate:
    """Compute a Candidate for one (ticker × risk × timeframe) tuple."""
    weights = cell_weights(risk_profile)
    analysis_dict = {name: r.to_dict() for name, r in module_results.items()}
    passes, reason = filter_for_profile(risk_profile, analysis_dict, asset_type)

    if not passes:
        return Candidate(
            ticker=ticker,
            asset_type=asset_type,
            risk_profile=risk_profile,
            timeframe=timeframe,
            cell_score=0.0,
            cell_confidence=0.0,
            direction="avoid",
            filter_passed=False,
            filter_reason=reason,
            notes=[f"Filtered: {reason}"],
            raw_module_scores={
                name: _compact_module(r) for name, r in module_results.items()
            },
        )

    weighted_sum = 0.0
    weight_sum = 0.0
    confidence_num = 0.0
    confidence_den = 0.0
    contributors: list[dict] = []
    notes: list[str] = []

    for name, result in module_results.items():
        w_cell = weights.get(name, 0.0)
        w_horizon = result.horizon_weights.get(timeframe, 0.0)
        if w_cell <= 0 or w_horizon <= 0:
            continue
        if result.score is None or result.confidence <= 0:
            continue

        # Effective weight × signal — module confidence dampens its
        # contribution; horizon_w gates by timeframe relevance.
        effective_w = w_cell * w_horizon
        weighted_sum += effective_w * result.score * result.confidence
        weight_sum += effective_w * result.confidence

        confidence_num += effective_w * result.confidence
        confidence_den += effective_w

        contributors.append({
            "module": name,
            "score": result.score,
            "confidence": result.confidence,
            "horizon_w": w_horizon,
            "cell_w": w_cell,
            "weighted_contrib": round(effective_w * result.score * result.confidence, 4),
        })

        # Surface a few notes from the modules that contributed most
        if result.notes:
            notes.extend(result.notes[:2])

    # Apply event_awareness penalty for THIS timeframe specifically.
    event = module_results.get("event_awareness")
    confidence_penalty = 0.0
    if event:
        per_tf = (event.raw or {}).get("by_timeframe", {}).get(timeframe, {})
        if per_tf.get("earnings_in_window"):
            confidence_penalty = 0.15
            notes.append(
                f"Earnings {per_tf['earnings_in_window'][0]} falls inside "
                f"{timeframe} window — confidence reduced."
            )

    if weight_sum <= 0 or confidence_den <= 0:
        # No usable signals
        return Candidate(
            ticker=ticker,
            asset_type=asset_type,
            risk_profile=risk_profile,
            timeframe=timeframe,
            cell_score=0.0,
            cell_confidence=0.0,
            direction="avoid",
            notes=notes + ["No usable module signals for this cell."],
            raw_module_scores={
                name: _compact_module(r) for name, r in module_results.items()
            },
        )

    cell_score = weighted_sum / weight_sum
    cell_confidence = (confidence_num / confidence_den) - confidence_penalty
    cell_confidence = max(0.0, min(1.0, cell_confidence))

    direction = _direction_from_cell(cell_score, cell_confidence)

    # Sort contributors by |weighted_contrib| desc for display
    contributors.sort(key=lambda c: abs(c["weighted_contrib"]), reverse=True)

    return Candidate(
        ticker=ticker,
        asset_type=asset_type,
        risk_profile=risk_profile,
        timeframe=timeframe,
        cell_score=round(cell_score, 4),
        cell_confidence=round(cell_confidence, 4),
        direction=direction,
        contributors=contributors[:8],
        notes=notes[:8],
        raw_module_scores={
            name: _compact_module(r) for name, r in module_results.items()
        },
    )


def _direction_from_cell(score: float, confidence: float) -> str:
    """Map cell-level score+confidence to a Buy / Avoid / Sell-short label."""
    if confidence < MIN_CONFIDENCE:
        return "avoid"
    if score >= DIRECTION_THRESHOLD:
        return "buy"
    if score <= -DIRECTION_THRESHOLD:
        return "sell_short"
    return "avoid"


def _compact_module(r: ModuleResult) -> dict:
    """Slim per-module summary stored on the Candidate."""
    return {
        "score": r.score,
        "direction": r.direction,
        "confidence": r.confidence,
        "data_quality": r.data_quality,
    }


# ---------------------------------------------------------------------------
# Per-cell ranking
# ---------------------------------------------------------------------------
def rank_candidates(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Order candidates strongest → weakest by signal strength × confidence."""
    return sorted(
        list(candidates),
        key=lambda c: (
            abs(c.cell_score) * c.cell_confidence,
            c.cell_confidence,
        ),
        reverse=True,
    )


def top_n_per_cell(
    candidates: Iterable[Candidate],
    *,
    min_buys: int = 3,
    min_sell_shorts: int = 1,
    max_total: int = 8,
) -> list[Candidate]:
    """Pick top candidates with directional balance.

    Goal: at least 3 buys + 1 sell-short (when signals exist), padded with
    'avoid' candidates only if we don't have enough buys/sells. Caps at
    max_total to keep LLM workload bounded.
    """
    ranked = rank_candidates(candidates)
    buys = [c for c in ranked if c.direction == "buy"]
    sells = [c for c in ranked if c.direction == "sell_short"]
    avoids = [c for c in ranked if c.direction == "avoid" and c.filter_passed]

    out: list[Candidate] = []
    out.extend(buys[:max(min_buys, math.ceil(max_total * 0.6))])
    out.extend(sells[:max(min_sell_shorts, math.ceil(max_total * 0.2))])
    # If we still don't have min_buys buys, that's life — surfaces honestly.
    # Pad with strongest avoids if room remains.
    remaining = max_total - len(out)
    if remaining > 0 and avoids:
        out.extend(avoids[:remaining])
    return out[:max_total]
