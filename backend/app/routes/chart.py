"""Chart page data: OHLCV bars per interval and symbol search."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WatchlistItem
from app.providers.registry import get_provider
from app.redact import redact_exc

router = APIRouter()

_CURATED = Path(__file__).resolve().parent.parent / "data" / "curated_etfs.json"


@router.get("/bars/{ticker}")
def chart_bars(ticker: str, interval: str = Query(default="1d")) -> dict:
    yf = get_provider("yfinance")
    if interval not in yf.CHART_INTERVALS:
        raise HTTPException(400, f"interval must be one of {list(yf.CHART_INTERVALS)}")
    try:
        data = yf.get_chart_bars(ticker.strip().upper(), interval)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"price data unavailable: {redact_exc(exc, 200)}") from exc
    if not data or not data.get("bars"):
        raise HTTPException(404, f"no price data for {ticker.upper()}")
    info = yf.get_info(ticker.strip().upper()) or {}
    return {**data, "name": info.get("long_name"), "exchange": info.get("exchange"),
            "currency": data.get("currency") or info.get("currency")}


@router.get("/symbols")
def chart_symbols(db: Session = Depends(get_db)) -> list[dict]:
    """The app's own universe — watchlist first, then curated ETFs."""
    out: dict[str, dict] = {}
    yf = get_provider("yfinance")
    for w in db.scalars(select(WatchlistItem)).all():
        try:
            name = (yf.get_info(w.ticker) or {}).get("long_name")  # cached 12h
        except Exception:  # noqa: BLE001
            name = None
        out[w.ticker] = {"symbol": w.ticker, "name": name, "source": "watchlist"}
    for e in json.loads(_CURATED.read_text(encoding="utf-8")).get("etfs", []):
        out.setdefault(e["ticker"], {"symbol": e["ticker"], "name": e.get("name"), "source": "curated"})
    return list(out.values())


@router.get("/search")
def chart_search(q: str = Query(min_length=1, max_length=40)) -> list[dict]:
    """Search any symbol on Yahoo (stocks, ETFs, indices, FX, crypto)."""
    try:
        return get_provider("yfinance").search_symbols(q.strip())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"search unavailable: {redact_exc(exc, 200)}") from exc
