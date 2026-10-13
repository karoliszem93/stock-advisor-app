"""Full analysis of one ticker, computed live: every module's reading and how
they combine into Buy / Avoid / Sell for each risk profile × timeframe.

Same snapshot, modules and per-cell scoring as the daily pipeline — only the
LLM write-up is skipped (and GDELT tone comes from cache, since its throttling
would stall an interactive request).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.registry import analyze_ticker
from app.config import get_settings
from app.db import get_db
from app.models import Suggestion, WatchlistItem
from app.providers.registry import get_provider
from app.services.snapshot import build_macro_context, build_ticker_context
from app.services.universe import UniverseEntry
from app.synthesis.scorer import DIRECTION_THRESHOLD, MIN_CONFIDENCE, score_candidate
from app.synthesis.weights import RISK_PROFILES, TIMEFRAMES, cell_weights

router = APIRouter()

_CURATED = Path(__file__).resolve().parent.parent / "data" / "curated_etfs.json"
_CACHE_TTL = 15 * 60
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _entry(ticker: str, db: Session) -> UniverseEntry:
    curated = {e["ticker"]: e for e in json.loads(_CURATED.read_text(encoding="utf-8")).get("etfs", [])}
    if ticker in curated:
        return UniverseEntry(ticker, "etf", "curated_etfs", metadata=curated[ticker])
    w = db.scalar(select(WatchlistItem).where(WatchlistItem.ticker == ticker))
    info = get_provider("yfinance").get_info(ticker) or {}
    return UniverseEntry(ticker, info.get("asset_type") or "equity", "watchlist" if w else "adhoc",
                         note=w.note if w else None)


@router.get("/{ticker}")
def full_analysis(ticker: str, refresh: bool = Query(default=False), db: Session = Depends(get_db)) -> dict:
    sym = ticker.strip().upper()
    with _lock:
        hit = _cache.get(sym)
    if hit and not refresh and time.time() - hit[0] < _CACHE_TTL:
        return {**hit[1], "cached": True}

    s = get_settings()
    today = datetime.now(ZoneInfo(s.timezone)).date()
    entry = _entry(sym, db)
    ctx = build_ticker_context(entry, today, macro=build_macro_context(), live_gdelt=False)
    if not (ctx.ohlcv or {}).get("bars"):
        raise HTTPException(404, f"no price data for {sym}")
    results = analyze_ticker(ctx)

    cells = []
    for risk in RISK_PROFILES:
        for tf in TIMEFRAMES:
            c = score_candidate(sym, ctx.asset_type, risk, tf, results)
            cells.append({
                "risk_profile": risk, "timeframe": tf, "direction": c.direction,
                "score": c.cell_score, "confidence": c.cell_confidence,
                "filter_passed": c.filter_passed, "filter_reason": c.filter_reason,
                "contributors": c.contributors, "notes": c.notes,
            })

    # the app's latest stored call for each cell (with the LLM thesis behind it)
    latest_date = db.scalar(select(Suggestion.suggestion_date).where(Suggestion.ticker == sym)
                            .order_by(Suggestion.suggestion_date.desc()).limit(1))
    stored = []
    if latest_date:
        for r in db.scalars(select(Suggestion).where(Suggestion.ticker == sym, Suggestion.suggestion_date == latest_date)):
            stored.append({"id": r.id, "risk_profile": r.risk_profile, "timeframe": r.timeframe,
                           "direction": r.direction, "confidence": r.confidence, "headline": r.headline})

    info = ctx.info or {}
    bars = ctx.ohlcv["bars"]
    out = {
        "ticker": sym,
        "name": info.get("long_name"),
        "asset_type": ctx.asset_type,
        "currency": info.get("currency") or ctx.ohlcv.get("currency"),
        "exchange": info.get("exchange"),
        "sector": info.get("sector"),
        "last_close": bars[-1].get("close"),
        "last_date": bars[-1].get("date"),
        "benchmark": (ctx.metadata or {}).get("benchmark"),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "modules": {name: r.to_dict() for name, r in results.items()},
        "profile_weights": {risk: cell_weights(risk) for risk in RISK_PROFILES},
        "cells": cells,
        "thresholds": {"direction": DIRECTION_THRESHOLD, "min_confidence": MIN_CONFIDENCE},
        "data_errors": ctx.errors,
        "stored": {"date": latest_date.isoformat() if latest_date else None, "cells": stored},
        "cached": False,
    }
    with _lock:
        _cache[sym] = (time.time(), out)
    return out
