"""Smoke tests for the analysis layer.

These don't assert specific numeric outputs — they just verify that:
  - Every module returns a ModuleResult with the expected shape
  - Empty / minimal contexts don't crash any module
  - The registry runs all applicable modules for both equity and ETF inputs
"""

from datetime import date, timedelta

from app.analysis.base import AnalysisContext, ModuleResult
from app.analysis.registry import analyze_ticker, list_modules


def _synthetic_bars(n: int = 400, start: float = 100.0) -> list[dict]:
    """Generate plausible OHLCV bars with a mild uptrend + noise."""
    import math

    bars = []
    today = date.today()
    price = start
    for i in range(n):
        d = today - timedelta(days=n - i)
        # gentle uptrend with sinusoidal noise
        price = price * (1 + 0.0006 + 0.005 * math.sin(i / 13))
        bars.append({
            "date": d.isoformat(),
            "open": price * 0.998,
            "high": price * 1.012,
            "low": price * 0.988,
            "close": price,
            "adj_close": price,
            "volume": 1_000_000 + (i % 7) * 50_000,
            "dividend": 0.0,
            "split_ratio": 0.0,
        })
    return bars


def _empty_context(asset_type: str = "equity") -> AnalysisContext:
    return AnalysisContext(
        ticker="TEST",
        asset_type=asset_type,
        snapshot_date=date.today(),
    )


def _populated_context(asset_type: str = "equity") -> AnalysisContext:
    bars = _synthetic_bars(400)
    return AnalysisContext(
        ticker="TEST",
        asset_type=asset_type,
        snapshot_date=date.today(),
        ohlcv={"ticker": "TEST", "currency": "USD", "bars": bars},
        info={
            "long_name": "Test Co", "currency": "USD", "exchange": "NYS",
            "sector": "Technology", "asset_type": asset_type, "market_cap": 1_000_000_000,
        },
        macro={
            "VIXCLS": {"value": 15.5, "delta_7d": -0.4},
            "DGS10": {"value": 4.10, "delta_7d": -0.05},
            "T10Y2Y": {"value": 0.40},
            "UNRATE": {"value": 3.8},
        },
        benchmark_ohlcv={"ticker": "SPY", "currency": "USD", "bars": _synthetic_bars(400, start=400)},
    )


def test_registry_lists_all_expected_modules():
    names = set(list_modules())
    expected = {
        "technical", "momentum", "mean_reversion", "volatility_regime",
        "risk_metrics", "fundamental_equity", "etf_fundamental", "quality",
        "news_sentiment", "social_sentiment", "insider_institutional",
        "macro", "event_awareness",
    }
    assert expected.issubset(names), f"missing: {expected - names}"


def test_empty_context_does_not_crash():
    ctx = _empty_context("equity")
    results = analyze_ticker(ctx)
    # Every applicable module should still return a ModuleResult
    assert all(isinstance(r, ModuleResult) for r in results.values())
    # And no module should have crashed (errors list empty)
    crashed = {k: r for k, r in results.items() if r.errors}
    assert not crashed, f"modules crashed on empty context: {crashed}"


def test_etf_runs_etf_module_not_equity_module():
    ctx = _populated_context("etf")
    results = analyze_ticker(ctx)
    assert "etf_fundamental" in results
    assert "fundamental_equity" not in results
    assert "quality" not in results  # equity-only


def test_equity_runs_equity_module_not_etf_module():
    ctx = _populated_context("equity")
    results = analyze_ticker(ctx)
    assert "fundamental_equity" in results
    assert "etf_fundamental" not in results


def test_technical_module_emits_score_with_full_bars():
    ctx = _populated_context("equity")
    results = analyze_ticker(ctx)
    tech = results["technical"]
    assert tech.score is not None
    assert -1.0 <= tech.score <= 1.0
    assert tech.direction in ("bullish", "bearish", "neutral")
    assert tech.data_quality in ("full", "partial")
    assert tech.horizon_weights  # non-empty


def test_macro_module_emits_score_with_bundle():
    ctx = _populated_context("equity")
    results = analyze_ticker(ctx)
    macro = results["macro"]
    assert macro.score is not None
    assert macro.raw["vix"] == 15.5
