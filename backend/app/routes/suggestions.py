"""Suggestion read endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Suggestion

router = APIRouter()


@router.get("/distinct-dates")
def distinct_dates(db: Session = Depends(get_db)) -> list[str]:
    rows = db.scalars(
        select(distinct(Suggestion.suggestion_date)).order_by(Suggestion.suggestion_date.desc())
    ).all()
    return [d.isoformat() for d in rows]


@router.get("/distinct-tickers")
def distinct_tickers(db: Session = Depends(get_db)) -> list[str]:
    rows = db.scalars(
        select(distinct(Suggestion.ticker)).order_by(Suggestion.ticker.asc())
    ).all()
    return list(rows)


@router.get("/by-ticker/{ticker}")
def suggestions_by_ticker(
    ticker: str,
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    """All suggestions for one ticker, latest first — powers the ticker view."""
    stmt = (
        select(Suggestion)
        .where(Suggestion.ticker == ticker.upper())
        .order_by(Suggestion.suggestion_date.desc(), Suggestion.timeframe.asc())
        .limit(limit)
    )
    rows = db.scalars(stmt).all()
    return [_row_to_dict(r) for r in rows]


@router.get("/")
def list_suggestions(
    db: Session = Depends(get_db),
    on_date: date | None = Query(default=None, description="Filter to suggestions made on this date"),
    risk: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict]:
    stmt = select(Suggestion).order_by(Suggestion.suggestion_date.desc(), Suggestion.confidence.desc())
    if on_date:
        stmt = stmt.where(Suggestion.suggestion_date == on_date)
    if risk:
        stmt = stmt.where(Suggestion.risk_profile == risk)
    if timeframe:
        stmt = stmt.where(Suggestion.timeframe == timeframe)
    if ticker:
        stmt = stmt.where(Suggestion.ticker == ticker.upper())
    if direction:
        stmt = stmt.where(Suggestion.direction == direction)
    stmt = stmt.limit(limit)
    rows = db.scalars(stmt).all()
    return [_row_to_dict(r) for r in rows]


@router.get("/{suggestion_id}")
def get_suggestion(suggestion_id: int, db: Session = Depends(get_db)) -> dict:
    s = db.get(Suggestion, suggestion_id)
    if s is None:
        return {"error": "not_found"}
    return _row_to_dict(s, full=True)


def _row_to_dict(s: Suggestion, full: bool = False) -> dict:
    out = {
        "id": s.id,
        "suggestion_date": s.suggestion_date.isoformat(),
        "ticker": s.ticker,
        "asset_type": s.asset_type,
        "timeframe": s.timeframe,
        "risk_profile": s.risk_profile,
        "direction": s.direction,
        "confidence": s.confidence,
        "confidence_calibrated": s.confidence_calibrated,
        "target_date": s.target_date.isoformat(),
        "headline": s.headline,
        "entry_price_eur": s.entry_price_eur,
        "stop_loss_eur": s.stop_loss_eur,
        "target_price_eur": s.target_price_eur,
        "suggested_risk_pct": s.suggested_risk_pct,
        "data_repo_commit_sha": s.data_repo_commit_sha,
    }
    if full:
        out["rationale"] = s.rationale
        out["suggestion_json_path"] = s.suggestion_json_path
        out["analysis_json_path"] = s.analysis_json_path
    return out
