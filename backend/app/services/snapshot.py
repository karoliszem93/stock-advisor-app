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
"""

from __future__ import annotations

import logging
from datetime import date

from app.analysis.base import AnalysisContext
from app.providers.registry import get_provider
from app.services.universe import UniverseEntry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-run building blocks
# ---------------------------------------------------------------------------
def build_macro_context() -> dict | None:
    """Fetch the FRED macro bundle once per run."""
    try:
        fred = get_provider("fred")
        if not fred.is_available():
            return None
        return fred.get_macro_bundle()
    except Exception as exc:  # noqa: BLE001
        log.warning("macro fetch failed: %s", exc)
        return None


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
    etf_info = None
    if asset_type == "etf":
        etf_info = _safe(errors, "fmp.etf_info", lambda: get_provider("fmp").get_etf_info(ticker))

    # ---- fundamentals (equities only) ----
    fundamentals = None
    if asset_type == "equity":
        fundamentals = _build_unified_fundamentals(ticker, errors)

    # ---- news ----
    news: list[dict] = []
    fh_news = _safe(errors, "finnhub.news", lambda: get_provider("finnhub").get_company_news(ticker, days=14))
    if fh_news:
        news.extend(fh_news)
    # Finnhub aggregate sentiment is a paid endpoint — always 403 on free tier.
    # We rely on the news_sentiment module's keyword polarity over the headlines instead.
    sentiment_score = None

    # ---- social (only if Reddit configured) ----
    social = []
    reddit = get_provider("reddit")
    if reddit.is_available():
        social = _safe(errors, "reddit.search", lambda: reddit.search_ticker(ticker)) or []

    # ---- insider ----
    insider = _build_insider_summary(ticker, errors) if asset_type == "equity" else None

    # ---- upcoming events ----
    earnings = _safe(errors, "finnhub.earnings_cal",
                     lambda: get_provider("finnhub").get_earnings_calendar(ticker, days_ahead=120))
    upcoming_events = {
        "earnings": [
            {"date": e.get("date"), "estimate": e.get("epsEstimate"), "fiscal_period": e.get("quarter")}
            for e in (earnings or [])
        ],
        "ex_dividend": [],   # populated when we wire dividend calendar in Phase 2.5
        "fomc": [],          # populated from FRED later if useful
    }

    # The module reads finnhub_sentiment from ctx.metadata — stash it there.
    md = dict(entry.metadata or {})
    if sentiment_score is not None:
        md["finnhub_sentiment"] = sentiment_score
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
        errors[key] = repr(exc)[:200]
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
    if not start or start == 0 or end is None or n_years <= 0:
        return None
    try:
        return float((end / start) ** (1 / n_years) - 1)
    except (ZeroDivisionError, ValueError):
        return None
