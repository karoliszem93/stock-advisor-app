"""Chart page data: OHLCV bars per interval, symbol search, and technical-analysis rules."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.ta import rules as ta
from app.analysis.ta.benchmarks import benchmark_for
from app.db import get_db
from app.models import WatchlistItem
from app.providers.registry import get_provider
from app.redact import redact_exc

router = APIRouter()

_CURATED = Path(__file__).resolve().parent.parent / "data" / "curated_etfs.json"

# chart interval -> (pandas resample rule for the higher timeframe, label)
_HTF = {
    "15m": ("1h", "1H"), "1h": ("4h", "4H"), "4h": ("1D", "Daily"),
    "1d": ("W-FRI", "Weekly"), "1wk": ("ME", "Monthly"), "1mo": ("QE", "Quarterly"),
}
# rule overlays are sent for the most recent bars only (indicators still warm up on all of them)
_TA_MAX_BARS = 2000


def _curated() -> dict[str, dict]:
    return {e["ticker"]: e for e in json.loads(_CURATED.read_text(encoding="utf-8")).get("etfs", [])}


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
    for e in _curated().values():
        out.setdefault(e["ticker"], {"symbol": e["ticker"], "name": e.get("name"), "source": "curated"})
    return list(out.values())


@router.get("/search")
def chart_search(q: str = Query(min_length=1, max_length=40)) -> list[dict]:
    """Search any symbol on Yahoo (stocks, ETFs, indices, FX, crypto)."""
    try:
        return get_provider("yfinance").search_symbols(q.strip())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"search unavailable: {redact_exc(exc, 200)}") from exc


@router.get("/ta/{ticker}")
def chart_ta(ticker: str, interval: str = Query(default="1d")) -> dict:
    """Technical-analysis rules on the chart's bars: per-rule state at the last bar,
    historical buy/sell events, overlays, and the module scores they add up to —
    the same engine the daily pipeline scores with."""
    yf = get_provider("yfinance")
    if interval not in yf.CHART_INTERVALS:
        raise HTTPException(400, f"interval must be one of {list(yf.CHART_INTERVALS)}")
    sym = ticker.strip().upper()
    try:
        data = yf.get_chart_bars(sym, interval)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"price data unavailable: {redact_exc(exc, 200)}") from exc
    if not data or len(data.get("bars") or []) < 30:
        raise HTTPException(404, f"not enough price data for {sym}")

    df = ta.build_frame(data["bars"], "time")
    info = yf.get_info(sym) or {}
    meta = _curated().get(sym, {})
    bench = benchmark_for(sym, category=meta.get("category"), country=info.get("country"),
                          asset_type=info.get("asset_type") or "equity")
    bench_series = None
    if bench and bench[0] != sym:
        try:
            bench_bars = yf.get_chart_bars(bench[0], interval)
            bench_series = ta.align_benchmark(df, (bench_bars or {}).get("bars"), "time")
        except Exception:  # noqa: BLE001 — relative strength just shows as unavailable
            bench_series = None

    htf_rule, htf_label = _HTF[interval]
    outs = ta.evaluate(df, benchmark=bench_series, benchmark_name=bench[1] if bench else None,
                       htf_rule=htf_rule, htf_label=htf_label)
    out = ta.serialize(outs, list(df["time"]), start=max(0, len(df) - _TA_MAX_BARS))
    tech = ta.aggregate_technical(outs)
    mr = ta.aggregate_mean_reversion(outs)
    out["summary"] = {
        "technical": {"score": tech["score"], "amplifier": tech["amplifier"],
                      "htf_state": tech["htf_state"], "htf_conflict": tech["htf_conflict"]},
        "mean_reversion": {"score": mr["score"]},
        "relative_strength": {"score": outs["relative_strength"].score,
                              "benchmark": bench[1] if bench else None},
        "interval": interval,
        "bars_evaluated": len(df),
    }
    return out
