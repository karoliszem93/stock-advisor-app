"""Volatility regime module.

Classifies the ticker's current realized volatility against its own history:
  - "low"     vol percentile < 25
  - "normal"  25–75
  - "high"    75–95
  - "extreme" > 95

This module's *score* is small — volatility is mostly used to MODULATE
other modules' confidence, not to generate a buy/sell signal directly.
A high-vol regime mildly reduces confidence on technical signals (more
noise) and mildly biases against aggressive long entries (worse risk-
adjusted return). An extreme-vol regime is reported as a strong negative
signal for the conservative profile in the synthesis layer.
"""

from __future__ import annotations

import pandas as pd

from app.analysis.base import (
    AnalysisContext,
    BaseAnalysisModule,
    ModuleResult,
    clamp,
    direction_from_score,
    no_data,
)


class VolatilityRegimeModule(BaseAnalysisModule):
    name = "volatility_regime"
    description = "Realized vol percentile vs ticker's own 2y history."

    HORIZON_WEIGHTS = {
        "1w": 0.7, "2w": 0.7, "1m": 0.6, "3m": 0.5,
        "6m": 0.4, "1y": 0.3, "3y": 0.2,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        bars = (ctx.ohlcv or {}).get("bars") if ctx.ohlcv else None
        if not bars or len(bars) < 252:
            r = no_data(self.name, "need >= 1y of bars for vol percentile")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        closes = pd.Series([b.get("adj_close") or b.get("close") for b in bars])
        closes.index = pd.to_datetime([b["date"] for b in bars])
        closes = closes.sort_index()
        rets = closes.pct_change().dropna()

        # 30-day rolling annualized vol
        vol_30d = rets.tail(30).std() * (252 ** 0.5)
        vol_history = rets.rolling(30).std() * (252 ** 0.5)
        vol_history = vol_history.dropna().tail(504)  # ~2y
        if len(vol_history) < 60:
            r = no_data(self.name, "insufficient history for vol percentile")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        percentile = float((vol_history < vol_30d).mean())
        regime = _classify(percentile)

        # Realized 30d vol in plain percent terms
        vol_30d_pct = float(vol_30d * 100)

        s = 0.0
        notes: list[str] = []
        if regime == "extreme":
            s = -0.20
            notes.append(f"Volatility extreme — 30d realized {vol_30d_pct:.1f}% (>95th pctile).")
        elif regime == "high":
            s = -0.10
            notes.append(f"Volatility elevated — 30d realized {vol_30d_pct:.1f}% (75–95 pctile).")
        elif regime == "low":
            s = +0.05
            notes.append(f"Volatility subdued — 30d realized {vol_30d_pct:.1f}% (<25 pctile).")

        return ModuleResult(
            module=self.name,
            score=clamp(s),
            direction=direction_from_score(s, threshold=0.05),
            confidence=0.7,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "vol_30d_pct": round(vol_30d_pct, 2),
                "percentile_2y": round(percentile, 3),
                "regime": regime,
            },
            notes=notes,
            data_quality="full",
        )


def _classify(percentile: float) -> str:
    if percentile < 0.25:
        return "low"
    if percentile < 0.75:
        return "normal"
    if percentile < 0.95:
        return "high"
    return "extreme"
