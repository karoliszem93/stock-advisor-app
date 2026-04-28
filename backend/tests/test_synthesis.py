"""Synthesis-layer tests.

These don't require Ollama or any provider — they exercise the pure-Python
scoring, pricing, and weight logic.
"""

from datetime import date

from app.analysis.base import ModuleResult
from app.synthesis.pricing import price_cell
from app.synthesis.scorer import (
    DIRECTION_THRESHOLD,
    Candidate,
    score_candidate,
    top_n_per_cell,
)
from app.synthesis.weights import (
    RISK_PROFILES,
    TIMEFRAMES,
    cell_weights,
    filter_for_profile,
    timeframe_to_target_date,
)


def _module(name: str, score: float, conf: float = 0.7,
            horizon_w: dict | None = None,
            quality: str = "full",
            raw: dict | None = None) -> ModuleResult:
    return ModuleResult(
        module=name,
        score=score,
        confidence=conf,
        direction="bullish" if score > 0 else "bearish" if score < 0 else "neutral",
        horizon_weights=horizon_w or {tf: 1.0 for tf in TIMEFRAMES},
        data_quality=quality,
        raw=raw or {},
    )


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------
def test_all_risk_profiles_have_weight_for_every_module():
    """Every risk profile should at least DEFINE every analysis module's
    weight (even if zero) so we don't silently drop modules."""
    expected_modules = {
        "technical", "momentum", "mean_reversion", "volatility_regime",
        "risk_metrics", "fundamental_equity", "etf_fundamental", "quality",
        "news_sentiment", "social_sentiment", "insider_institutional",
        "macro", "event_awareness",
    }
    for risk in RISK_PROFILES:
        weights = cell_weights(risk)
        missing = expected_modules - set(weights.keys())
        assert not missing, f"{risk} missing weights for: {missing}"


def test_weight_emphasis_matches_risk_philosophy():
    """Spot-check: aggressive weights momentum more than conservative does."""
    cons = cell_weights("conservative")
    agg = cell_weights("aggressive")
    assert agg["momentum"] > cons["momentum"] * 3
    assert cons["quality"] > agg["quality"] * 2
    assert cons["risk_metrics"] > agg["risk_metrics"]


def test_timeframe_to_target_date_offsets():
    today = date(2026, 4, 28)
    assert (timeframe_to_target_date(today, "1w") - today).days == 7
    assert (timeframe_to_target_date(today, "1m") - today).days == 30
    assert (timeframe_to_target_date(today, "1y") - today).days == 365


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------
def test_score_candidate_passes_filters_for_clean_data():
    """A clean equity with positive technical + fundamental signals should
    score positive for Growth / 1m and yield a 'buy'."""
    modules = {
        "technical":          _module("technical", 0.5, 0.7),
        "momentum":           _module("momentum", 0.4, 0.7),
        "fundamental_equity": _module("fundamental_equity", 0.3, 0.6),
        "quality":            _module("quality", 0.4, 0.7),
        "risk_metrics":       _module("risk_metrics", 0.0, 0.8,
                                      raw={"beta_3y": 1.2, "max_drawdown_3y_pct": -25}),
        "macro":              _module("macro", 0.1, 0.6),
    }
    cand = score_candidate("AAPL", "equity", "growth", "1m", modules)
    assert cand.filter_passed
    assert cand.cell_score > DIRECTION_THRESHOLD
    assert cand.direction == "buy"
    assert cand.cell_confidence > 0.3


def test_conservative_filter_rejects_high_beta():
    modules = {
        "technical":          _module("technical", 0.4),
        "fundamental_equity": _module("fundamental_equity", 0.2),
        "risk_metrics":       _module("risk_metrics", 0.0, 0.8,
                                      raw={"beta_3y": 1.8, "max_drawdown_3y_pct": -25}),
        "quality":            _module("quality", 0.0, 0.5,
                                      raw={"piotroski_f": 6, "altman_z": 4}),
    }
    cand = score_candidate("HOTSTOCK", "equity", "conservative", "1m", modules)
    assert not cand.filter_passed
    assert cand.direction == "avoid"
    assert "beta" in (cand.filter_reason or "")


def test_negative_signal_yields_sell_short():
    modules = {
        "technical":          _module("technical", -0.5, 0.7),
        "momentum":           _module("momentum", -0.5, 0.7),
        "fundamental_equity": _module("fundamental_equity", -0.3, 0.6),
        "quality":            _module("quality", -0.4, 0.6, raw={"piotroski_f": 6}),
        "risk_metrics":       _module("risk_metrics", 0.0, 0.8, raw={"beta_3y": 1.2}),
    }
    cand = score_candidate("BADCO", "equity", "growth", "1m", modules)
    assert cand.cell_score < -DIRECTION_THRESHOLD
    assert cand.direction == "sell_short"


def test_top_n_per_cell_balances_directions():
    candidates = [
        Candidate("A", "equity", "growth", "1m", 0.30, 0.7, "buy"),
        Candidate("B", "equity", "growth", "1m", 0.25, 0.6, "buy"),
        Candidate("C", "equity", "growth", "1m", 0.20, 0.6, "buy"),
        Candidate("D", "equity", "growth", "1m", 0.15, 0.5, "buy"),
        Candidate("E", "equity", "growth", "1m", -0.30, 0.6, "sell_short"),
        Candidate("F", "equity", "growth", "1m", 0.05, 0.5, "avoid"),
    ]
    top = top_n_per_cell(candidates, max_total=6)
    tickers = [c.ticker for c in top]
    # Should include >=3 buys + the sell-short
    assert "A" in tickers and "B" in tickers and "C" in tickers
    assert "E" in tickers


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
def test_price_cell_buy_with_eur_conversion():
    macro = {"DEXUSEU": {"value": 1.07}}  # 1.07 USD per 1 EUR  → 1 USD = 0.9346 EUR
    pc = price_cell(
        direction="buy",
        last_close=200.0,
        atr=4.0,
        currency="USD",
        timeframe="1m",
        risk_profile="balanced",
        confidence=0.6,
        macro_bundle=macro,
    )
    assert pc.entry == 200.0
    assert pc.stop_loss < 200.0  # stop below for a buy
    assert pc.target > 200.0     # target above
    # ATR=4, target_atr_mult for 1m=3.5 → +14
    assert abs(pc.target - 214.0) < 0.01
    # FX: 1/1.07 = 0.9346
    assert abs(pc.fx_rate_used - 0.9346) < 0.001
    assert pc.entry_eur is not None
    # Sizing: balanced base 1.0% × confidence_mult (0.5 + 0.6 = 1.1) = 1.1%
    assert abs(pc.suggested_risk_pct - 0.011) < 0.0001


def test_price_cell_sell_short_inverts():
    pc = price_cell(
        direction="sell_short",
        last_close=100.0,
        atr=2.0,
        currency="EUR",
        timeframe="1m",
        risk_profile="aggressive",
        confidence=0.7,
        macro_bundle=None,
    )
    assert pc.stop_loss > pc.entry  # stop ABOVE for short
    assert pc.target < pc.entry      # target BELOW for short


def test_price_cell_falls_back_when_atr_missing():
    pc = price_cell(
        direction="buy",
        last_close=50.0,
        atr=None,
        currency="EUR",
        timeframe="1w",
        risk_profile="balanced",
        confidence=0.5,
        macro_bundle=None,
    )
    assert any("ATR unavailable" in n for n in pc.notes)
    assert pc.stop_loss < pc.entry
    assert pc.target > pc.entry


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def test_filter_aggressive_accepts_anything():
    analysis = {
        "risk_metrics": {"raw": {"beta_3y": 3.5, "max_drawdown_3y_pct": -80}},
        "quality": {"raw": {"piotroski_f": 1}},
        "volatility_regime": {"raw": {"regime": "extreme"}},
    }
    passes, reason = filter_for_profile("aggressive", analysis, "equity")
    assert passes is True
    assert reason is None


def test_filter_balanced_rejects_extreme_drawdown():
    analysis = {
        "risk_metrics": {"raw": {"beta_3y": 1.2, "max_drawdown_3y_pct": -75}},
        "quality": {"raw": {"piotroski_f": 7}},
        "volatility_regime": {"raw": {"regime": "normal"}},
    }
    passes, reason = filter_for_profile("balanced", analysis, "equity")
    assert passes is False
    assert "drawdown" in (reason or "")
