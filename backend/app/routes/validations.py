"""Validation history endpoints — populated in Phase 4."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import SuggestionValidation

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
            "target_hit": v.target_hit,
            "stop_hit": v.stop_hit,
            "ticker": v.suggestion.ticker if v.suggestion else None,
            "timeframe": v.suggestion.timeframe if v.suggestion else None,
            "risk_profile": v.suggestion.risk_profile if v.suggestion else None,
        }
        for v in rows
    ]


@router.get("/aggregate")
def aggregate_performance(db: Session = Depends(get_db)) -> dict:
    """Return rolling accuracy / hit-rate. Stub — populated in Phase 4."""
    # In Phase 4 we'll compute this from SuggestionValidation rows grouped by
    # (risk_profile, timeframe), and also include calibration plots.
    return {
        "ready": False,
        "reason": "Phase 4 not yet implemented — no validations to aggregate.",
    }
