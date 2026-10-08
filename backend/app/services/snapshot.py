"""Snapshot stage — fetch all provider data for one ticker into an AnalysisContext.

Three building blocks:

  - build_macro_context()       — global FRED bundle (per-run)
  - build_benchmark_ohlcv()     — benchmark price series (per-run)
  - build_ticker_context(...)   — full per-ticker context

Each provider call is wrapped in try/except. Failures are captured into
ctx.errors[provider_name] = "<reason>" so the analysis layer (and the
data-repo manifest) can mark suggestions as data-degraded.

Fundamentals unification: FMP is preferred (richest fields, 250/day free).
Alpha Vantage and EDGAR are fallbacks. The unified shape is what the
fundamental_equity + quality modules consume.

Non-US listings (London/Xetra ETFs, European equities): the free tiers of
Finnhub, FMP, Alpha Vantage and EDGAR only cover US symbols and reject these
outright, so we don't call them. Instead news comes from Google News (+ NewsAPI
for equities), and fundamentals / earnings dates from Yahoo.
"""

from __future__ import annotations

import logging
from datetime import date

from app.analysis.base import AnalysisContext
from app.providers.registry import get_provider
from app.redact import redact_exc
from app.services.universe import UniverseEntry

log = logging.getLogger(__name__)

# Yahoo exchange suffixes for non-US listings ("VUSA.L", "BNP.PA", "VWCE.DE").
# Single-letter US share classes like "BRK.B" are deliberately not listed.
_NON_US_SUFFIXES = {
    "L", "IL", "PA", "DE", "F", "AS", "MI", "MC", "SW", "VI", "BR", "LS", "HE",
    "ST", "CO", "OL", "IR", "WA", "PR", "AT", "TO", "V", "NE", "AX", "NZ", "HK",
    "T", "KS", "KQ", "SS", "SZ", "TW", "SI", "NS", "BO", "SA", "MX", "JO",
}

# News for an ETF is really news about what it holds — search by exposure.
_ETF_NEWS_QUERIES = {
    "global_developed_em": '"global stocks" OR "world stocks"',
    "global_developed": '"global stocks" OR "MSCI World"',
    "us_large_cap": '"S&P 500"',
    "us_tech": '"Nasdaq 100" OR "Nasdaq-100"',
    "global_dividend": '"dividend stocks"',
    "emerging_markets": '"emerging markets" stocks',
    "europe_developed": '"European stocks" OR "Stoxx 600"',
    "japan": '"Japanese stocks" OR Nikkei OR Topix',
    "bonds_global": '"bond market" OR "global bonds"',
    "commodities_gold": '"gold price"',
    "factor_quality": '"quality stocks" OR "quality factor"',
    "factor_value": '"value stocks"',
    "factor_momentum": '"momentum stocks"',
    "factor_low_vol": '"low volatility" stocks',
    "us_sector_tech": '"tech stocks"',
    "us_sector_financials": '"bank stocks" OR "financial stocks"',
    "us_sector_health": '"healthcare stocks"',
    "us_sector_energy": '"energy stocks" OR "oil prices"',
    "us_sector_staples": '"consumer staples"',
    "us_sector_discretionary": '"consumer discretionary" OR "retail stocks"',
    "bonds_us_treasury": '"Treasury yields"',
    "bonds_eu_govt": '"Bund yields" OR "euro zone bonds"',
    "bonds_eu_corp": '"corporate bonds" Europe',
    "thematic_clean_energy": '"clean energy" stocks',
    "thematic_automation": 'robotics OR automation stocks',
    "thematic_ev": '"electric vehicle" stocks',
}


def is_us_listed(ticker: str) -> bool:
    return "." not in ticker or ticker.rsplit(".", 1)[1].upper() not in _NON_US_SUFFIXES


def _news_query(entry: UniverseEntry, asset_type: str, info: dict | None) -> str | None:
    if asset_type == "etf":
        q = _ETF_NEWS_QUERIES.get((entry.metadata or {}).get("category", ""))
        if q:
            return q
    name = (info or {}).get("long_name") or (entry.metadata or {}).get("name")
    if not name:
        return None
    # "Vanguard S&P 500 UCITS ETF (Distributing)" -> "Vanguard S&P 500"
    for cut in (" UCITS", " ETF", " ("):
        name = name.split(cut)[0]
    return f'"{name.strip()}"'


# ---------------------------------------------------------------------------
# Per-run building blocks
# ---------------------------------------------------------------------------
def build_macro_context() -> dict | None:
    """Fetch the macro bundle once per run: FRED (US) + ECB/Eurostat/STOXX (euro area)."""
    macro: dict = {}
    try:
        fred = get_provider("fred")
        if fred.is_available():
            macro.update(fred.get_macro_bundle() or {})
    except Exception as exc:  # noqa: BLE001
        log.warning("FRED macro fetch failed: %s", exc)
    try:
        macro.update(get_provider("euromacro").get_bundle() or {})
    except Exception as exc:  # noqa: BLE001
        log.warning("euro macro fetch failed: %s", exc)
    return macro or None


def build_benchmark_ohlcv(benchmark: str = "SPY") -> dict | None:
    """Pull SPY (default) bars to compute relative-strength signals."""
    try:
        yf = get_provider("yfinance")
        return yf.get_ohlcv(benchmark, lookback_days=800)
    except Exception as exc:  # noqa: BLE001
        log.warning("benchmark fetch failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Per-ticker context build
# ---------------------------------------------------------------------------
def build_ticker_context(
    entry: UniverseEntry,
    snapshot_date: date,
    *,
    macro: dict | None = None,
    benchmark_ohlcv: dict | None = None,
) -> AnalysisContext:
    """Construct a full AnalysisContext for one ticker."""
    errors: dict[str, str] = {}
    ticker = entry.ticker.upper()

    # ---- prices + info ----
    ohlcv = _safe(errors, "yfinance.ohlcv", lambda: get_provider("yfinance").get_ohlcv(ticker, 800))
    info = _safe(errors, "yfinance.info", lambda: get_provider("yfinance").get_info(ticker))

    # If yfinance reports the asset is an ETF, override the entry classification.
    asset_type = entry.asset_type
    if info and info.get("asset_type") == "etf":
        asset_type = "etf"

    # ---- ETF-specific block ----
    us = is_us_listed(ticker)
    yf = get_provider("yfinance")
    etf_info = None
    if asset_type == "etf":
        if us:
            etf_info = _safe(errors, "fmp.etf_info", lambda: get_provider("fmp").get_etf_info(ticker))
        # physical commodity ETCs (gold etc.) have no holdings to report
        if not (entry.metadata or {}).get("category", "").startswith("commodities"):
            holdings = _safe(errors, "yfinance.holdings", lambda: yf.get_fund_holdings(ticker))
            if holdings:
                etf_info = {**(etf_info or {}), **holdings}

    # ---- fundamentals (equities only) ----
    fundamentals = None
    if asset_type == "equity":
        fundamentals = (
            _build_unified_fundamentals(ticker, errors) if us
            else _build_yahoo_fundamentals(ticker, errors)
        )
        fundamentals = _add_yahoo_extras(ticker, fundamentals, errors)

    # ---- news ----
    news: list[dict] = []
    if us:
        fh_news = _safe(errors, "finnhub.news", lambda: get_provider("finnhub").get_company_news(ticker, days=14))
        news.extend(fh_news or [])
    else:
        query = _news_query(entry, asset_type, info)
        if query:
            news.extend(_safe(errors, "googlenews", lambda: get_provider("googlenews").search(query)) or [])
            newsapi = get_provider("newsapi")
            # NewsAPI's free tier is 100/day — spend it on single stocks, not ETF themes
            if asset_type == "equity" and newsapi.is_available():
                articles = _safe(errors, "newsapi", lambda: newsapi.search_everything(query, days=14)) or []
                seen = {n["headline"].lower() for n in news}
                news.extend(a for a in articles if (a.get("title") or "").lower() not in seen)
    # Finnhub aggregate sentiment is a paid endpoint — always 403 on free tier.
    # We rely on the news_sentiment module's keyword polarity over the headlines instead.
    sentiment_score = None

    # GDELT average tone (global, multilingual) — best-effort, often throttled
    gdelt_tone = None
    tone_query = _news_query(entry, asset_type, info)
    if tone_query:
        gdelt_tone = _safe(errors, "gdelt", lambda: get_provider("gdelt").get_tone(tone_query))

    # ---- social (only if Reddit configured) ----
    social = []
    reddit = get_provider("reddit")
    if reddit.is_available():
        social = _safe(errors, "reddit.search", lambda: reddit.search_ticker(ticker)) or []

    # ---- insider ----
    # EDGAR / Finnhub insider data only exists for US issuers
    insider = _build_insider_summary(ticker, errors) if asset_type == "equity" and us else None
    if asset_type == "equity":
        ownership = _safe(errors, "yfinance.ownership", lambda: yf.get_ownership(ticker)) or {}
        if us:
            si = _safe(errors, "finra.short_interest", lambda: get_provider("finra").get_short_interest(ticker))
            if si:
                ownership = {**ownership, **si}
        if ownership:
            insider = {**(insider or {}), "ownership": ownership}

    # ---- upcoming events ----
    # ETFs don't report earnings or publish an ex-dividend calendar
    calendar = (_safe(errors, "yfinance.calendar", lambda: yf.get_calendar(ticker)) or {}) \
        if asset_type == "equity" else {}
    if us and asset_type == "equity":
        earnings = _safe(errors, "finnhub.earnings_cal",
                         lambda: get_provider("finnhub").get_earnings_calendar(ticker, days_ahead=120))
        earnings = earnings or calendar.get("earnings")
    else:
        earnings = calendar.get("earnings")
    upcoming_events = {
        "earnings": [
            {"date": e.get("date"), "estimate": e.get("epsEstimate"), "fiscal_period": e.get("quarter")}
            for e in (earnings or [])
        ],
        "ex_dividend": calendar.get("ex_dividend") or [],
        "fomc": [],          # populated from FRED later if useful
    }

    # The module reads finnhub_sentiment from ctx.metadata — stash it there.
    md = dict(entry.metadata or {})
    if sentiment_score is not None:
        md["finnhub_sentiment"] = sentiment_score
    if gdelt_tone:
        md["gdelt_tone"] = gdelt_tone
    if entry.note:
        md["note"] = entry.note
    md["source"] = entry.source

    return AnalysisContext(
        ticker=ticker,
        asset_type=asset_type,
        snapshot_date=snapshot_date,
        metadata=md,
        ohlcv=ohlcv,
        info=info,
        fundamentals=fundamentals,
        etf_info=etf_info,
        news=news,
        social=social,
        macro=macro,
        insider=insider,
        upcoming_events=upcoming_events,
        benchmark_ohlcv=benchmark_ohlcv,
        sector_ohlcv=None,  # sector benchmark resolution is a Phase 2.5 enhancement
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Fundamentals unifier
# ---------------------------------------------------------------------------
def _build_unified_fundamentals(ticker: str, errors: dict) -> dict | None:
    """Combine FMP + Alpha Vantage + SimFin into the shape consumed by
    fundamental_equity / quality modules.

    FMP is preferred when available (richest, fastest); Alpha Vantage acts
    as a fallback for the TTM ratios when FMP is rate-limited.
    """
    fmp = get_provider("fmp")
    av = get_provider("alphavantage")

    fmp_ratios = _safe(errors, "fmp.ratios", lambda: fmp.get_ratios_ttm(ticker)) if fmp.is_available() else None
    fmp_metrics = _safe(errors, "fmp.metrics", lambda: fmp.get_key_metrics_ttm(ticker)) if fmp.is_available() else None
    fmp_income = _safe(errors, "fmp.income", lambda: fmp.get_income_statement(ticker, 5)) if fmp.is_available() else None
    fmp_balance = _safe(errors, "fmp.balance", lambda: fmp.get_balance_sheet(ticker, 5)) if fmp.is_available() else None
    fmp_cashflow = _safe(errors, "fmp.cashflow", lambda: fmp.get_cash_flow(ticker, 5)) if fmp.is_available() else None

    av_overview = None
    if not fmp_ratios and not fmp_metrics:
        av_overview = _safe(errors, "av.overview", lambda: av.get_overview(ticker)) if av.is_available() else None

    if not (fmp_ratios or fmp_metrics or av_overview):
        return None

    ttm: dict = {}
    if fmp_ratios:
        ttm.update({
            "pe": _f(fmp_ratios.get("priceEarningsRatioTTM")),
            "pb": _f(fmp_ratios.get("priceToBookRatioTTM")),
            "ps": _f(fmp_ratios.get("priceToSalesRatioTTM")),
            "peg": _f(fmp_ratios.get("priceEarningsToGrowthRatioTTM")),
            "ev_ebitda": _f(fmp_ratios.get("enterpriseValueMultipleTTM")),
            "debt_to_equity": _f(fmp_ratios.get("debtEquityRatioTTM")),
            "roe": _f(fmp_ratios.get("returnOnEquityTTM")),
            "roic": _f(fmp_ratios.get("returnOnCapitalEmployedTTM")),
            "gross_margin": _f(fmp_ratios.get("grossProfitMarginTTM")),
            "op_margin": _f(fmp_ratios.get("operatingProfitMarginTTM")),
            "net_margin": _f(fmp_ratios.get("netProfitMarginTTM")),
        })
    if fmp_metrics:
        ttm.setdefault("fcf_yield", _f(fmp_metrics.get("freeCashFlowYieldTTM")))
        ttm.setdefault("ev_ebitda", _f(fmp_metrics.get("enterpriseValueOverEBITDATTM")))

    if av_overview:
        ttm.setdefault("pe", _f(av_overview.get("PERatio")))
        ttm.setdefault("pb", _f(av_overview.get("PriceToBookRatio")))
        ttm.setdefault("ps", _f(av_overview.get("PriceToSalesRatioTTM")))
        ttm.setdefault("peg", _f(av_overview.get("PEGRatio")))
        ttm.setdefault("roe", _f(av_overview.get("ReturnOnEquityTTM")))

    growth = {}
    if fmp_income and len(fmp_income) >= 4:
        revs = [r.get("revenue") for r in fmp_income[:4] if r.get("revenue")]
        eps = [r.get("eps") for r in fmp_income[:4] if r.get("eps")]
        growth["rev_3y"] = _cagr(revs)
        growth["eps_3y"] = _cagr(eps)

    return {
        "ttm": ttm,
        "growth": growth,
        "earnings_history": [],  # Finnhub-sourced earnings history is a follow-up
        "income_periods": fmp_income or [],
        "balance_sheet_periods": fmp_balance or [],
        "cash_flow_periods": fmp_cashflow or [],
        "source": "fmp" if fmp_ratios else "alphavantage",
    }


def _build_yahoo_fundamentals(ticker: str, errors: dict) -> dict | None:
    """TTM ratios from Yahoo for listings the free fundamentals APIs don't cover.

    No multi-year statements, so growth and the statement-based quality
    checks stay empty (those modules report partial data).
    """
    ratios = _safe(errors, "yfinance.ratios", lambda: get_provider("yfinance").get_key_ratios(ticker))
    if not ratios or not any(v is not None for v in ratios.values()):
        return None
    return {
        "ttm": ratios,
        "growth": {},
        "earnings_history": [],
        "income_periods": [],
        "balance_sheet_periods": [],
        "cash_flow_periods": [],
        "source": "yahoo",
    }


def _add_yahoo_extras(ticker: str, fundamentals: dict | None, errors: dict) -> dict | None:
    """Fill gaps from Yahoo: multi-year statements (when FMP had none), growth
    computed from them, earnings surprises, and analyst consensus."""
    yf = get_provider("yfinance")
    f = dict(fundamentals or {"ttm": {}, "growth": {}, "source": "yahoo"})

    if not f.get("income_periods"):
        st = _safe(errors, "yfinance.statements", lambda: yf.get_statements(ticker)) or {}
        if st:
            f["income_periods"] = st.get("income") or []
            f["balance_sheet_periods"] = st.get("balance") or []
            f["cash_flow_periods"] = st.get("cashflow") or []
            f["statements_source"] = "yahoo"
    growth = dict(f.get("growth") or {})
    income = f.get("income_periods") or []
    if len(income) >= 3:
        growth.setdefault("rev_3y", _cagr([r.get("revenue") for r in income[:4] if r.get("revenue")]))
        growth.setdefault("eps_3y", _cagr([r.get("eps") for r in income[:4] if r.get("eps")]))
    f["growth"] = {k: v for k, v in growth.items() if v is not None}

    if not f.get("earnings_history"):
        f["earnings_history"] = _safe(errors, "yfinance.earnings_history",
                                      lambda: yf.get_earnings_history(ticker)) or []
    analyst = _safe(errors, "yfinance.analyst", lambda: yf.get_analyst_view(ticker))
    if analyst:
        f["analyst"] = analyst

    has_data = f.get("ttm") or f.get("growth") or f.get("income_periods") or f.get("analyst")
    return f if has_data else fundamentals


# ---------------------------------------------------------------------------
# Insider unifier
# ---------------------------------------------------------------------------
def _build_insider_summary(ticker: str, errors: dict) -> dict | None:
    edgar = get_provider("edgar")
    finnhub = get_provider("finnhub")

    edgar_summary = _safe(errors, "edgar.insider", lambda: edgar.get_insider_form4_summary(ticker, days=90))
    fh_insider = (
        _safe(errors, "finnhub.insider", lambda: finnhub.get_insider_transactions(ticker, days=90))
        if finnhub.is_available() else None
    )

    if not edgar_summary and not fh_insider:
        return None

    buys, sells = 0, 0
    net_value = 0.0
    transactions = []

    if isinstance(fh_insider, dict):
        for t in (fh_insider.get("data") or []):
            shares = t.get("share") or 0
            change = t.get("change") or 0
            txn_code = (t.get("transactionCode") or "").upper()
            if txn_code in {"P", "A"} or change > 0:  # P=purchase, A=acquisition
                buys += 1
            elif txn_code == "S" or change < 0:
                sells += 1
            transactions.append({
                "date": t.get("filingDate"),
                "code": txn_code,
                "share": shares,
                "change": change,
                "transactionPrice": t.get("transactionPrice"),
            })
            try:
                net_value += float(change) * float(t.get("transactionPrice") or 0)
            except (TypeError, ValueError):
                pass

    if edgar_summary:
        # form4 count rough proxy if Finnhub not available
        if not buys and not sells:
            buys = edgar_summary.get("form4_filings", 0) // 2
            sells = edgar_summary.get("form4_filings", 0) - buys

    return {
        "insider_buys_90d": buys,
        "insider_sells_90d": sells,
        "net_value_usd_90d": net_value,
        "net_share_change_pct": None,  # could compute given shares_outstanding
        "transactions_sample": transactions[:20],
        "source": "finnhub+edgar" if fh_insider else "edgar",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe(errors: dict, key: str, fn):
    """Call fn(); on any exception, record the error and return None."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        errors[key] = redact_exc(exc, 200)
        log.debug("snapshot %s failed: %s", key, exc)
        return None


def _f(x) -> float | None:
    if x is None or x == "" or x == "None":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _cagr(values: list[float]) -> float | None:
    """Compound annual growth rate from the most-recent → oldest list of period values."""
    if not values or len(values) < 2:
        return None
    # values are listed most-recent first (FMP convention)
    end = values[0]
    start = values[-1]
    n_years = len(values) - 1
    if not start or start <= 0 or end is None or end <= 0 or n_years <= 0:
        return None
    try:
        return float((end / start) ** (1 / n_years) - 1)
    except (ZeroDivisionError, ValueError):
        return None
