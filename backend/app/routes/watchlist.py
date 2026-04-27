"""Watchlist CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WatchlistItem

router = APIRouter()


class WatchlistItemIn(BaseModel):
    ticker: str
    note: str | None = None


@router.get("/")
def list_items(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(WatchlistItem).order_by(WatchlistItem.ticker)).all()
    return [{"ticker": r.ticker, "note": r.note} for r in rows]


@router.post("/")
def add_item(item: WatchlistItemIn, db: Session = Depends(get_db)) -> dict:
    ticker = item.ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Empty ticker")
    existing = db.get(WatchlistItem, ticker)
    if existing:
        existing.note = item.note
    else:
        db.add(WatchlistItem(ticker=ticker, note=item.note))
    db.commit()
    return {"ticker": ticker, "note": item.note}


@router.delete("/{ticker}")
def remove_item(ticker: str, db: Session = Depends(get_db)) -> dict:
    ticker = ticker.strip().upper()
    row = db.get(WatchlistItem, ticker)
    if row is None:
        raise HTTPException(404, "Not found")
    db.delete(row)
    db.commit()
    return {"removed": ticker}
