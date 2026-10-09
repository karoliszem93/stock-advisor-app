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
    rate_limit_capacity = 5000  # self-imposed politeness cap per day (pipeline + chart browsing)
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
        cache_key = f"ohlcv:v2:{ticker.upper()}:{lookback_days}"  # v2: empty bars dropped

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
                # Yahoo sometimes returns a placeholder row with no prices (e.g. the
                # previous session for European listings, early in the morning).
                # Keeping it makes the "last close" NaN, which blanks every price
                # derived from it and poisons indicators.
                if _num(row.get("Close")) is None:
                    continue
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

    # interval -> (yfinance interval, history period, cache TTL seconds, resample rule)
    CHART_INTERVALS = {
        "15m": ("15m", "60d", 300, None),
        "1h": ("60m", "730d", 600, None),
        "4h": ("60m", "730d", 600, "4h"),
        "1d": ("1d", "max", 3600, None),
        "1wk": ("1wk", "max", 6 * 3600, None),
        "1mo": ("1mo", "max", 6 * 3600, None),
    }

    def get_chart_bars(self, ticker: str, interval: str = "1d") -> dict | None:
        """OHLCV for the chart page, as many bars as Yahoo allows for the interval.

        `time` is a UTC unix timestamp for intraday intervals and "YYYY-MM-DD"
        for daily and longer (the chart library treats those as calendar days).
        """
        if interval not in self.CHART_INTERVALS:
            raise ValueError(f"unsupported interval {interval!r}")
        yf_interval, period, ttl, resample = self.CHART_INTERVALS[interval]
        cache_key = f"chart:{ticker.upper()}:{interval}"

        def _fetch():
            t = yf.Ticker(ticker)
            df = t.history(period=period, interval=yf_interval, auto_adjust=False)
            if df is None or df.empty:
                return None
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
            if resample:
                df = df.resample(resample).agg(
                    {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
                ).dropna(subset=["Close"])
            intraday = yf_interval.endswith("m")
            bars = []
            for idx, row in df.iterrows():
                bars.append({
                    "time": int(idx.timestamp()) if intraday else idx.date().isoformat(),
                    "open": _num(row["Open"]),
                    "high": _num(row["High"]),
                    "low": _num(row["Low"]),
                    "close": _num(row["Close"]),
                    "volume": _num(row["Volume"]) or 0,
                })
            currency = ""
            try:
                currency = t.fast_info.get("currency") or ""
            except Exception:  # noqa: BLE001
                pass
            return {"ticker": ticker.upper(), "interval": interval, "currency": currency, "bars": bars}

        return self.cached_request(cache_key, ttl_seconds=ttl, fetch=_fetch)

    def search_symbols(self, query: str, limit: int = 10) -> list[dict]:
        """Yahoo symbol search (any listing worldwide)."""
        cache_key = f"search:{query.lower()}:{limit}"

        def _fetch():
            quotes = yf.Search(query, max_results=limit, news_count=0).quotes or []
            return [
                {
                    "symbol": q.get("symbol"),
                    "name": q.get("shortname") or q.get("longname"),
                    "exchange": q.get("exchDisp") or q.get("exchange"),
                    "type": (q.get("quoteType") or "").lower(),
                }
                for q in quotes
                if q.get("symbol") and q.get("quoteType") in ("EQUITY", "ETF", "INDEX", "MUTUALFUND", "CURRENCY", "CRYPTOCURRENCY", "FUTURE")
            ]

        return self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch) or []

    def get_info(self, ticker: str) -> dict | None:
        """Return basic descriptive info: name, sector, industry, exchange,
        market cap, currency, ETF holdings (when applicable).
        """
        cache_key = f"info:v2:{ticker.upper()}"  # v2: expense_ratio as a fraction

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
                # annualReportExpenseRatio is a fraction; netExpenseRatio is in percent (0.07 = 0.07%)
                "expense_ratio": info.get("annualReportExpenseRatio") or (
                    info["netExpenseRatio"] / 100 if info.get("netExpenseRatio") is not None else None
                ),
                "category": info.get("category"),
                "total_assets": info.get("totalAssets"),
            }

        return self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch)

    def get_key_ratios(self, ticker: str) -> dict | None:
        """TTM valuation / profitability ratios from Yahoo's quote summary.

        Fallback fundamentals for listings FMP / Alpha Vantage free tiers don't
        cover (e.g. European equities). Ratios are decimals; Yahoo's
        debtToEquity is a percentage and is converted.
        """
        cache_key = f"ratios:{ticker.upper()}"

        def _fetch():
            info = dict(yf.Ticker(ticker).get_info() or {})
            if not info:
                return None
            de = _num(info.get("debtToEquity"))
            fcf, mcap = _num(info.get("freeCashflow")), _num(info.get("marketCap"))
            gross = _num(info.get("grossMargins"))
            return {
                "pe": _num(info.get("trailingPE")),
                "pb": _num(info.get("priceToBook")),
                "ps": _num(info.get("priceToSalesTrailing12Months")),
                "peg": _num(info.get("trailingPegRatio") or info.get("pegRatio")),
                "ev_ebitda": _num(info.get("enterpriseToEbitda")),
                "debt_to_equity": de / 100 if de is not None else None,
                "roe": _num(info.get("returnOnEquity")),
                # banks/insurers report 0 gross margin — treat as unknown
                "gross_margin": gross or None,
                "op_margin": _num(info.get("operatingMargins")),
                "net_margin": _num(info.get("profitMargins")),
                "fcf_yield": fcf / mcap if fcf is not None and mcap else None,
            }

        return self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch)

    def get_calendar(self, ticker: str) -> dict | None:
        """Upcoming earnings and ex-dividend dates (works for non-US listings).

        Output: {"earnings": [{"date","epsEstimate","quarter"}], "ex_dividend": [{"date"}]}
        """
        cache_key = f"calendar:{ticker.upper()}"

        def _fetch():
            cal = yf.Ticker(ticker).calendar or {}
            today = date.today()
            exdiv = cal.get("Ex-Dividend Date")
            return {
                "earnings": [
                    {"date": d.isoformat(), "epsEstimate": _num(cal.get("Earnings Average")), "quarter": None}
                    for d in (cal.get("Earnings Date") or []) if d >= today
                ],
                "ex_dividend": [{"date": exdiv.isoformat()}] if exdiv and exdiv >= today else [],
            }

        return self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch)

    def get_statements(self, ticker: str) -> dict | None:
        """Annual income / balance / cash-flow statements, most recent first.

        Rows use FMP's field names so the quality + growth code reads them
        unchanged. Yahoo has ~4 years; banks lack some rows (current assets etc.).
        """
        cache_key = f"statements:{ticker.upper()}"

        def _fetch():
            t = yf.Ticker(ticker)
            out = {
                "income": _periods(t.income_stmt, _INCOME_ROWS),
                "balance": _periods(t.balance_sheet, _BALANCE_ROWS),
                "cashflow": _periods(t.cashflow, _CASHFLOW_ROWS),
            }
            return out if any(out.values()) else None

        return self.cached_request(cache_key, ttl_seconds=7 * 24 * 3600, fetch=_fetch)

    def get_earnings_history(self, ticker: str) -> list[dict] | None:
        """Last reported quarters, most recent first: [{"date","eps_actual","eps_estimate","surprise_pct"}]."""
        cache_key = f"earnings_history:{ticker.upper()}"

        def _fetch():
            df = yf.Ticker(ticker).earnings_history
            if df is None or df.empty:
                return []
            rows = []
            for idx, r in df.sort_index(ascending=False).iterrows():
                rows.append({
                    "date": idx.date().isoformat() if hasattr(idx, "date") else str(idx),
                    "eps_actual": _num(r.get("epsActual")),
                    "eps_estimate": _num(r.get("epsEstimate")),
                    "surprise_pct": _num(r.get("surprisePercent")),
                })
            return rows

        return self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch)

    def get_analyst_view(self, ticker: str) -> dict | None:
        """Analyst consensus: recommendation counts (current month) and price targets."""
        cache_key = f"analyst:{ticker.upper()}"

        def _fetch():
            t = yf.Ticker(ticker)
            out: dict[str, Any] = {}
            recs = t.recommendations
            if recs is not None and not recs.empty:
                cur = recs.iloc[0]
                out["recommendations"] = {
                    k: _int(cur.get(k)) or 0 for k in ("strongBuy", "buy", "hold", "sell", "strongSell")
                }
            targets = t.analyst_price_targets or {}
            if targets.get("mean"):
                out["price_target"] = {k: _num(targets.get(k)) for k in ("current", "mean", "median", "low", "high")}
            return out or None

        return self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch)

    def get_fund_holdings(self, ticker: str) -> dict | None:
        """ETF top-10 holdings and sector weights (decimals)."""
        cache_key = f"fund_holdings:{ticker.upper()}"

        def _fetch():
            f = yf.Ticker(ticker).funds_data
            top = f.top_holdings
            holdings = []
            if top is not None and not top.empty:
                holdings = [
                    {"symbol": sym, "name": r.get("Name"), "weight": _num(r.get("Holding Percent"))}
                    for sym, r in top.iterrows()
                ]
            sectors = {k: _num(v) for k, v in (f.sector_weightings or {}).items() if _num(v)}
            if not holdings and not sectors:
                return None
            return {
                "top_holdings": holdings,
                "top10_weight": sum(h["weight"] or 0 for h in holdings[:10]) or None,
                "sector_weights": sectors,
            }

        return self.cached_request(cache_key, ttl_seconds=7 * 24 * 3600, fetch=_fetch)

    def get_ownership(self, ticker: str) -> dict | None:
        """Short interest + institutional/insider ownership from Yahoo's quote summary."""
        cache_key = f"ownership:{ticker.upper()}"

        def _fetch():
            info = dict(yf.Ticker(ticker).get_info() or {})
            out = {
                "short_pct_float": _num(info.get("shortPercentOfFloat")),
                "short_ratio_days": _num(info.get("shortRatio")),
                "float_shares": _num(info.get("floatShares")),
                "held_pct_institutions": _num(info.get("heldPercentInstitutions")),
                "held_pct_insiders": _num(info.get("heldPercentInsiders")),
            }
            return out if any(v is not None for v in out.values()) else None

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
            # yfinance returns an exchange-tz-aware index; compare on naive wall time
            idx = ser.index.tz_localize(None) if ser.index.tz is not None else ser.index
            ser = ser[idx >= cutoff]
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


# Yahoo statement row -> FMP field name (what quality / growth code reads)
_INCOME_ROWS = {
    "Total Revenue": "revenue",
    "Cost Of Revenue": "costOfRevenue",
    "Gross Profit": "grossProfit",
    "Operating Income": "operatingIncome",
    "Net Income": "netIncome",
    "Diluted EPS": "eps",
}
_BALANCE_ROWS = {
    "Total Assets": "totalAssets",
    "Current Assets": "totalCurrentAssets",
    "Current Liabilities": "totalCurrentLiabilities",
    "Total Liabilities Net Minority Interest": "totalLiabilities",
    "Long Term Debt": "longTermDebt",
    "Total Debt": "totalDebt",
    "Retained Earnings": "retainedEarnings",
    "Stockholders Equity": "totalStockholdersEquity",
    "Ordinary Shares Number": "shares",
}
_CASHFLOW_ROWS = {
    "Operating Cash Flow": "operatingCashFlow",
    "Capital Expenditure": "capitalExpenditure",
    "Free Cash Flow": "freeCashFlow",
}


def _periods(df: pd.DataFrame | None, rows: dict[str, str]) -> list[dict]:
    """Yahoo statement frame (rows = items, columns = period ends) -> list of
    period dicts, most recent first. Periods with no mapped values are dropped."""
    if df is None or df.empty:
        return []
    out = []
    for col in sorted(df.columns, reverse=True):
        period = {"date": col.date().isoformat() if hasattr(col, "date") else str(col)}
        for yahoo_row, field in rows.items():
            if yahoo_row in df.index:
                period[field] = _num(df.at[yahoo_row, col])
        if any(v is not None for k, v in period.items() if k != "date"):
            out.append(period)
    return out

