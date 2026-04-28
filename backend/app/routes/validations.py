"""Validation history + aggregate performance endpoints."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Suggestion, SuggestionValidation
from app.synthesis.weights import RISK_PROFILES, TIMEFRAMES

router = APIRouter()


@router.get("/")
def list_validations(
    db: Session = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict]:
    stmt = (
        select(SuggestionValidation)
        .options(joinedload(SuggestionValidation.suggestion))
        .order_by(SuggestionValidation.validated_at.desc())
        .limit(limit)
    )
    rows = db.scalars(stmt).all()
    return [
        {
            "id": v.id,
            "suggestion_id": v.suggestion_id,
            "validated_at": v.validated_at.isoformat(),
            "outcome": v.outcome,
            "outcome_score": v.outcome_score,
            "actual_total_return_pct_eur": v.actual_total_return_pct_eur,
            "after_tax_return_pct_eur": v.after_tax_return_pct_eur,
            "actual_price_return_pct": v.actual_price_return_pct,
            "actual_dividend_return_pct": v.actual_dividend_return_pct,
            "actual_fx_effect_pct": v.actual_fx_effect_pct,
            "max_favorable_excursion_pct": v.max_favorable_excursion_pct,
            "max_adverse_excursion_pct": v.max_adverse_excursion_pct,
            "target_hit": v.target_hit,
            "stop_hit": v.stop_hit,
            "ticker": v.suggestion.ticker if v.suggestion else None,
            "timeframe": v.suggestion.timeframe if v.suggestion else None,
            "risk_profile": v.suggestion.risk_profile if v.suggestion else None,
            "direction": v.suggestion.direction if v.suggestion else None,
            "confidence": v.suggestion.confidence if v.suggestion else None,
            "confidence_calibrated": v.suggestion.confidence_calibrated if v.suggestion else None,
        }
        for v in rows
    ]


@router.get("/aggregate")
def aggregate_performance(db: Session = Depends(get_db)) -> dict:
    """Return rolling accuracy / hit-rate by (risk × timeframe) and overall."""
    rows = db.execute(
        select(Suggestion, SuggestionValidation)
        .join(SuggestionValidation, SuggestionValidation.suggestion_id == Suggestion.id)
    ).all()

    if not rows:
        return {
            "ready": False,
            "reason": "no validations yet",
            "total_validated": 0,
            "by_cell": {},
            "overall": {},
        }

    by_cell: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    overall_outcomes: list[str] = []
    overall_scores: list[float] = []
    overall_returns: list[float] = []

    for sug, val in rows:
        cell_key = f"{sug.risk_profile}.{sug.timeframe}"
        by_cell[cell_key]["outcomes"].append(val.outcome)
        by_cell[cell_key]["scores"].append(val.outcome_score or 0.0)
        if val.actual_total_return_pct_eur is not None:
            by_cell[cell_key]["returns_eur"].append(val.actual_total_return_pct_eur)
        overall_outcomes.append(val.outcome)
        overall_scores.append(val.outcome_score or 0.0)
        if val.actual_total_return_pct_eur is not None:
            overall_returns.append(val.actual_total_return_pct_eur)

    cell_summary: dict[str, dict[str, Any]] = {}
    for key, lists in by_cell.items():
        n = len(lists["outcomes"])
        cell_summary[key] = {
            "n": n,
            "hit_rate": round(_hit_rate(lists["outcomes"]), 4),
            "mean_outcome_score": round(sum(lists["scores"]) / n, 4) if n else 0.0,
            "mean_return_pct_eur": (
                round(sum(lists["returns_eur"]) / len(lists["returns_eur"]), 4)
                if lists["returns_eur"] else None
            ),
        }

    return {
        "ready": True,
        "total_validated": len(rows),
        "overall": {
            "hit_rate": round(_hit_rate(overall_outcomes), 4),
            "mean_outcome_score": round(sum(overall_scores) / len(overall_scores), 4),
            "mean_return_pct_eur": (
                round(sum(overall_returns) / len(overall_returns), 4)
                if overall_returns else None
            ),
        },
        "by_cell": cell_summary,
    }


def _hit_rate(outcomes: list[str]) -> float:
    if not outcomes:
        return 0.0
    correct = sum(1 for o in outcomes if o == "correct")
    return correct / len(outcomes)
