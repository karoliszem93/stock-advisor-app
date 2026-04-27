"""Yahoo Finance via yfinance — OHLCV, dividends, splits, basic info.

Free, no key. yfinance scrapes Yahoo so it's a bit fragile but very widely
used. We treat Yahoo's dividend-adjusted close as the truth for total return.

Rate limit: politely throttled by us (we set a generous in-house cap so we
don't hammer Yahoo if a loop misbehaves).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from app.providers.base import BaseProvider

log = logging.getLogger(__name__)


class YFinanceProvider(BaseProvider):
    name = "yfinance"
    description = "Yahoo Finance — prices, splits, dividends, basic info (no key)."
    rate_limit_capacity = 2000  # self-imposed politeness cap per day
    rate_limit_window_seconds = 86400

    def is_available(self) -> bool:
        return True

    def required_key_setting(self) -> str | None:
        return None

    # ------------------------------------------------------------------
    def get_ohlcv(self, ticker: str, lookback_days: int = 800) -> dict | None:
        """Return adjusted OHLCV bars for `ticker` over the lookback window.

        Output: {"ticker", "currency", "bars": [{"date","open","high","low",
        "close","adj_close","volume"}, ...]}.

        Cached for 12h. The daily pipeline runs once a day so 12h is enough
        to dedupe within-day re-runs without serving stale prices.
        """
        cache_key = f"ohlcv:{ticker.upper()}:{lookback_days}"

        def _fetch():
            end = date.today() + timedelta(days=1)
            start = end - timedelta(days=lookback_days)
            t = yf.Ticker(ticker)
            df: pd.DataFrame = t.history(
                start=start, end=end, auto_adjust=False, actions=True
            )
            if df is None or df.empty:
                return None
            currency = (t.fast_info.get("currency") if hasattr(t, "fast_info") else None) or ""
            bars = []
            for idx, row in df.iterrows():
                bars.append({
                    "date": idx.date().isoformat(),
                    "open": _num(row.get("Open")),
                    "high": _num(row.get("High")),
                    "low": _num(row.get("Low")),
                    "close": _num(row.get("Close")),
                    "adj_close": _num(row.get("Adj Close") if "Adj Close" in row else row.get("Close")),
                    "volume": _int(row.get("Volume")),
                    "dividend": _num(row.get("Dividends", 0.0)),
                    "split_ratio": _num(row.get("Stock Splits", 0.0)),
                })
            return {"ticker": ticker.upper(), "currency": currency, "bars": bars}

        return self.cached_request(cache_key, ttl_seconds=12 * 3600, fetch=_fetch)

    def get_info(self, ticker: str) -> dict | None:
        """Return basic descriptive info: name, sector, industry, exchange,
        market cap, currency, ETF holdings (when applicable).
        """
        cache_key = f"info:{ticker.upper()}"

        def _fetch():
            t = yf.Ticker(ticker)
            info: dict[str, Any] = {}
            try:
                info = dict(t.get_info() or {})
            except Exception as exc:  # noqa: BLE001
                log.debug("yfinance get_info(%s) failed: %s", ticker, exc)
            return {
                "ticker": ticker.upper(),
                "long_name": info.get("longName") or info.get("shortName"),
                "currency": info.get("currency"),
                "exchange": info.get("exchange"),
                "country": info.get("country"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "asset_type": ("etf" if info.get("quoteType") == "ETF" else "equity"),
                "market_cap": info.get("marketCap"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "fund_family": info.get("fundFamily"),
                "isin": info.get("isin"),
                # ETF-only fields:
                "expense_ratio": info.get("annualReportExpenseRatio") or info.get("netExpenseRatio"),
                "category": info.get("category"),
                "total_assets": info.get("totalAssets"),
            }

        return self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch)

    def get_dividends(self, ticker: str, years: int = 5) -> list[dict] | None:
        """Historical dividend payments. Used for tax-aware return splits."""
        cache_key = f"dividends:{ticker.upper()}:{years}"

        def _fetch():
            t = yf.Ticker(ticker)
            ser = t.dividends
            if ser is None or ser.empty:
                return []
            cutoff = datetime.now() - timedelta(days=365 * years)
            ser = ser[ser.index >= cutoff]
            return [{"date": idx.date().isoformat(), "amount": float(v)} for idx, v in ser.items()]

        return self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch)


def _num(v) -> float | None:
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v) -> int | None:
    n = _num(v)
    return int(n) if n is not None else None
