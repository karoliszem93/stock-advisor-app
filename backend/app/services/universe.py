"""Universe resolution — combines watchlist + curated ETF list.

The watchlist is user-managed (CRUD via /api/watchlist).
The curated ETF list is bundled (app/data/curated_etfs.json).

resolve_universe() returns the deduplicated set of tickers to analyze on
a given run, with their declared asset_type and any pre-known metadata
(domicile, distribution policy) so analysis modules can specialize.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WatchlistItem


@dataclass
class UniverseEntry:
    ticker: str
    asset_type: str          # "equity" | "etf"
    source: str              # "watchlist" | "curated_etfs"
    note: str | None = None
    metadata: dict | None = None


def _load_curated_etfs() -> list[dict]:
    path = Path(__file__).parent.parent / "data" / "curated_etfs.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)["etfs"]


def resolve_universe(db: Session) -> list[UniverseEntry]:
    """Return the union of (watchlist tickers + curated ETFs), deduplicated."""
    seen: dict[str, UniverseEntry] = {}

    # watchlist (treated as equity by default; analyzers can re-classify if it's an ETF)
    for item in db.scalars(select(WatchlistItem)).all():
        seen[item.ticker.upper()] = UniverseEntry(
            ticker=item.ticker.upper(),
            asset_type="equity",  # tentative; analysis can correct via yfinance get_info
            source="watchlist",
            note=item.note,
        )

    # curated ETFs
    for entry in _load_curated_etfs():
        t = entry["ticker"].upper()
        if t in seen:
            # already in watchlist — keep watchlist precedence but enrich metadata
            seen[t].asset_type = "etf"
            seen[t].metadata = entry
        else:
            seen[t] = UniverseEntry(
                ticker=t,
                asset_type="etf",
                source="curated_etfs",
                metadata=entry,
            )

    return sorted(seen.values(), key=lambda e: e.ticker)
