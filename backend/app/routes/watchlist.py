"""Watchlist CRUD with ticker validation.

Every ticker that lands in the watchlist must resolve on yfinance — that's
the same data path the analysis pipeline uses, so anything that validates
here is guaranteed to be analyzable downstream. Saves the user from
silent failures when they mistype `BNP` (no suffix) instead of `BNP.PA`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WatchlistItem

router = APIRouter()
log = logging.getLogger(__name__)


class WatchlistItemIn(BaseModel):
    ticker: str
    note: str | None = None


# ---------------------------------------------------------------------------
# Validation helper — used by both the dedicated endpoint and POST.
# ---------------------------------------------------------------------------
def _validate_ticker(ticker: str) -> dict[str, Any]:
    """Verify a ticker resolves on Yahoo Finance.

    Returns a dict with:
      valid: bool
      ticker: normalized symbol (uppercase, trimmed)
      name / exchange / currency / asset_type / last_close: present when valid
      error: present when invalid
      suggestions: alternative tickers worth trying (when invalid)
    """
    t = (ticker or "").strip().upper()
    if not t:
        return {"valid": False, "ticker": t, "error": "empty ticker"}

    # Defer the import so a missing yfinance lib doesn't crash app startup.
    try:
        import yfinance as yf
    except ImportError:
        # If yfinance isn't installed (shouldn't happen in our env), skip
        # validation and let the user add at their own risk.
        log.warning("yfinance unavailable — skipping ticker validation")
        return {"valid": True, "ticker": t, "name": None, "exchange": None,
                "currency": None, "asset_type": "equity", "last_close": None,
                "warning": "yfinance not installed; ticker not verified"}

    try:
        yt = yf.Ticker(t)
        hist = yt.history(period="5d", auto_adjust=False)
    except Exception as exc:  # noqa: BLE001
        return {
            "valid": False,
            "ticker": t,
            "error": f"yfinance lookup failed: {exc!r}",
            "suggestions": _suggest_alternatives(t),
        }

    if hist is None or hist.empty:
        return {
            "valid": False,
            "ticker": t,
            "error": (
                f"No price data for '{t}' on Yahoo Finance. "
                f"The fund may exist on Trading 212 but be indexed under a "
                f"different Yahoo ticker — try one of the suggested alternatives."
            ),
            "suggestions": _suggest_alternatives(t),
        }

    info: dict = {}
    try:
        info = yt.get_info() or {}
    except Exception:  # noqa: BLE001
        # Some tickers have price data but get_info fails. Don't reject.
        pass

    last_close = float(hist["Close"].iloc[-1]) if not hist.empty else None
    return {
        "valid": True,
        "ticker": t,
        "name": info.get("longName") or info.get("shortName") or "",
        "exchange": info.get("exchange") or "",
        "currency": info.get("currency") or "",
        "asset_type": "etf" if info.get("quoteType") == "ETF" else "equity",
        "last_close": last_close,
    }


def _suggest_alternatives(ticker: str) -> list[str]:
    """Common exchange-suffix variants worth trying."""
    if "." in ticker:
        # Already has a suffix — strip it and offer suffix-less + other suffixes
        base = ticker.split(".", 1)[0]
        return [base, f"{base}.L", f"{base}.DE", f"{base}.AS", f"{base}.PA"]
    # No suffix — likely needs one for non-US listings
    return [f"{ticker}.L", f"{ticker}.DE", f"{ticker}.AS", f"{ticker}.PA", f"{ticker}.MI"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/")
def list_items(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(WatchlistItem).order_by(WatchlistItem.ticker)).all()
    return [{"ticker": r.ticker, "note": r.note} for r in rows]


@router.get("/validate/{ticker}")
def validate_ticker_endpoint(ticker: str) -> dict:
    """Pre-flight check before adding. Frontend calls this on input blur or
    submit so users see the resolved ticker name + exchange before saving."""
    return _validate_ticker(ticker)


@router.post("/")
def add_item(item: WatchlistItemIn, db: Session = Depends(get_db)) -> dict:
    ticker = item.ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Empty ticker")

    validation = _validate_ticker(ticker)
    if not validation.get("valid"):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "TICKER_NOT_FOUND",
                "ticker": ticker,
                "message": validation.get("error", "Ticker validation failed"),
                "suggestions": validation.get("suggestions", []),
            },
        )

    existing = db.get(WatchlistItem, ticker)
    if existing:
        existing.note = item.note
    else:
        db.add(WatchlistItem(ticker=ticker, note=item.note))
    db.commit()

    return {
        "ticker": ticker,
        "note": item.note,
        "name": validation.get("name"),
        "exchange": validation.get("exchange"),
        "currency": validation.get("currency"),
        "asset_type": validation.get("asset_type"),
        "last_close": validation.get("last_close"),
    }


@router.delete("/{ticker}")
def remove_item(ticker: str, db: Session = Depends(get_db)) -> dict:
    ticker = ticker.strip().upper()
    row = db.get(WatchlistItem, ticker)
    if row is None:
        raise HTTPException(404, "Not found")
    db.delete(row)
    db.commit()
    return {"removed": ticker}
