"""Default per-cell module weights and timeframe constants.

Two-level weighting
-------------------
Each module has *intrinsic* horizon weights it declares (e.g. technical is
high on 1w and low on 3y). Synthesis multiplies those by *cell weights*
that depend on the user's risk profile:

    final_weight[module] = cell_weights[risk][module] * module.horizon_weights[tf]

Defaults are reasonable starting points, tuned by hand. Phase 4's
calibration loop overrides them in models/weights_history.jsonl based on
which modules' signals actually correlated with realized outcomes.

Risk-profile philosophy
-----------------------
Conservative — quality, fundamentals, risk-aware. Skeptical of momentum
                hype. Favors low-volatility names.
Balanced     — even mix; classic "growth at reasonable price" lean.
Growth       — momentum + news + fundamentals (growth metrics matter).
Aggressive   — momentum + social + technical short-term, high tolerance
                for volatility.
"""

from __future__ import annotations

from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RISK_PROFILES: tuple[str, ...] = ("conservative", "balanced", "growth", "aggressive")
TIMEFRAMES: tuple[str, ...] = ("1w", "2w", "1m", "3m", "6m", "1y", "3y")

TIMEFRAME_DAYS: dict[str, int] = {
    "1w": 7,
    "2w": 14,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "3y": 365 * 3,
}


def timeframe_to_target_date(snapshot_date: date, timeframe: str) -> date:
    return snapshot_date + timedelta(days=TIMEFRAME_DAYS[timeframe])


# ---------------------------------------------------------------------------
# Default cell weights — risk profile × module
# ---------------------------------------------------------------------------
# Each row sums to roughly 1.0 (we normalize later anyway). Modules not
# listed for a profile get weight 0 — meaning the module's signal is
# IGNORED for that risk profile (e.g. social_sentiment for Conservative).
_DEFAULT_CELL_WEIGHTS: dict[str, dict[str, float]] = {
    "conservative": {
        "quality":              0.20,
        "fundamental_equity":   0.20,
        "etf_fundamental":      0.20,
        "risk_metrics":         0.10,
        "macro":                0.10,
        "technical":            0.05,
        "momentum":             0.03,
        "mean_reversion":       0.03,
        "volatility_regime":    0.05,
        "news_sentiment":       0.02,
        "insider_institutional":0.02,
        "event_awareness":      0.00,  # adjusts confidence, not direction
        "social_sentiment":     0.00,  # ignored for conservative
    },
    "balanced": {
        "fundamental_equity":   0.16,
        "etf_fundamental":      0.16,
        "quality":              0.12,
        "technical":            0.10,
        "momentum":             0.10,
        "macro":                0.10,
        "risk_metrics":         0.07,
        "news_sentiment":       0.07,
        "mean_reversion":       0.05,
        "volatility_regime":    0.04,
        "insider_institutional":0.03,
        "event_awareness":      0.00,
        "social_sentiment":     0.00,
    },
    "growth": {
        "momentum":             0.18,
        "fundamental_equity":   0.15,
        "technical":            0.13,
        "news_sentiment":       0.10,
        "etf_fundamental":      0.10,
        "quality":              0.08,
        "macro":                0.08,
        "mean_reversion":       0.05,
        "volatility_regime":    0.05,
        "insider_institutional":0.04,
        "risk_metrics":         0.02,
        "social_sentiment":     0.02,
        "event_awareness":      0.00,
    },
    "aggressive": {
        "momentum":             0.22,
        "technical":            0.18,
        "news_sentiment":       0.12,
        "social_sentiment":     0.10,
        "mean_reversion":       0.10,
        "fundamental_equity":   0.08,
        "etf_fundamental":      0.05,
        "macro":                0.05,
        "quality":              0.04,
        "volatility_regime":    0.03,
        "insider_institutional":0.03,
        "risk_metrics":         0.00,
        "event_awareness":      0.00,
    },
}


def cell_weights(risk: str) -> dict[str, float]:
    """Return the module-weight dict for a risk profile."""
    if risk not in _DEFAULT_CELL_WEIGHTS:
        raise ValueError(f"Unknown risk profile: {risk}")
    return dict(_DEFAULT_CELL_WEIGHTS[risk])


# ---------------------------------------------------------------------------
# Risk filters — disqualify candidates that don't fit a risk profile.
# ---------------------------------------------------------------------------
# Each filter takes a per-ticker analysis dict and returns
# (passes: bool, reason: str | None).
def filter_for_profile(risk: str, analysis: dict, asset_type: str) -> tuple[bool, str | None]:
    """Apply hard filters per risk profile."""
    risk_metrics = (analysis.get("risk_metrics") or {}).get("raw") or {}
    quality = (analysis.get("quality") or {}).get("raw") or {}
    vol_regime = (analysis.get("volatility_regime") or {}).get("raw") or {}
    etf_meta = (analysis.get("etf_fundamental") or {}).get("raw") or {}

    beta = risk_metrics.get("beta_3y")
    max_dd = risk_metrics.get("max_drawdown_3y_pct")
    piotroski = quality.get("piotroski_f")
    regime = vol_regime.get("regime")

    if risk == "conservative":
        if beta is not None and beta > 1.4:
            return False, f"beta {beta:.2f} > 1.4 fails conservative filter"
        if regime == "extreme":
            return False, "extreme volatility fails conservative filter"
        if asset_type == "equity" and piotroski is not None and piotroski < 5:
            return False, f"Piotroski {piotroski} < 5 fails conservative filter"
        category = etf_meta.get("category") or ""  # tolerate None
        if category.startswith(("leveraged", "inverse")):
            return False, "leveraged/inverse ETF fails conservative filter"

    elif risk == "balanced":
        if beta is not None and beta > 2.0:
            return False, f"beta {beta:.2f} > 2.0 fails balanced filter"
        if max_dd is not None and max_dd < -65:
            return False, f"max drawdown {max_dd:.0f}% < -65% fails balanced filter"

    elif risk == "growth":
        # Lenient on volatility but still excludes obvious distress
        if asset_type == "equity" and piotroski is not None and piotroski <= 2:
            return False, f"Piotroski {piotroski} ≤ 2 — distress fails growth filter"

    # aggressive: no hard filters — anything goes
    return True, None
