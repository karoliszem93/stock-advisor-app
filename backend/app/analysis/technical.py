"""Technical analysis module.

Scores the chart with the shared rules engine (app/analysis/ta/rules.py) —
the same rules the Chart page draws, so a manual read of the chart matches
what was scored:

  Trend            price vs 200-EMA, ADX (14) strength + DI crosses
  Momentum         RSI (14) zones, MACD (12,26,9) crossovers
  Volume           volume-confirmed breakouts, OBV divergence/confirmation,
                   unusual-volume spikes
  Price levels     support/resistance bounces and rejections
  Patterns         candlesticks (engulfing, hammer, stars), chart patterns
                   (double top/bottom, bull/bear flags)
  Multi-timeframe  weekly trend — adds ±0.10 and damps daily signals that
                   fight it (×0.6)

Score = sum of rule contributions × ADX amplifier (×1.15 strong trend,
×0.85 no trend), then the weekly-conflict damping. Bollinger Bands live in
the mean-reversion module only (previously counted in both).
"""

from __future__ import annotations

from typing import Any

from app.analysis.base import (
    AnalysisContext,
    BaseAnalysisModule,
    ModuleResult,
    clamp,
    direction_from_score,
    no_data,
)
from app.analysis.ta import indicators as ind
from app.analysis.ta import rules as ta


class TechnicalModule(BaseAnalysisModule):
    name = "technical"
    description = "Chart rules: trend, RSI, MACD, ADX, volume, S/R, candlestick + chart patterns, weekly trend."
    applies_to = ("equity", "etf")

    # Technical signals are most useful on shorter horizons.
    HORIZON_WEIGHTS = {
        "1w": 1.0, "2w": 1.0, "1m": 0.85,
        "3m": 0.55, "6m": 0.35, "1y": 0.20, "3y": 0.10,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        bars = (ctx.ohlcv or {}).get("bars") if ctx.ohlcv else None
        if not bars or len(bars) < 60:
            r = no_data(self.name, "fewer than 60 daily bars available")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        df = ta.build_frame(bars, "date")
        outs = ta.evaluate(df, htf_rule="W-FRI", htf_label="Weekly")
        agg = ta.aggregate_technical(outs)
        score = clamp(agg["score"])

        adx = outs["adx"].meta.get("adx")
        sr = outs["support_resistance"].meta
        raw: dict[str, Any] = {
            "last_close": float(df["close"].iloc[-1]),
            "atr_14": _last(ind.atr(df, 14)),  # Wilder; pricing uses it for stop/target distances
            "rsi_14": _last(ind.rsi(df["close"], 14)),
            "adx_14": adx,
            "ema_200": _last(ind.ema(df["close"], 200)),
            "support_levels": [lv["price"] for lv in sr.get("support", [])],
            "resistance_levels": [lv["price"] for lv in sr.get("resistance", [])],
            "weekly_trend": agg["htf_state"],
            "weekly_conflict": agg["htf_conflict"],
            "adx_amplifier": agg["amplifier"],
            "rules": {
                k: {"score": round(outs[k].score, 3), "state": outs[k].state, "status": outs[k].status}
                for k in ta.TECHNICAL_RULES
            },
        }

        confidence = 0.6
        if adx is not None and adx > 25:
            confidence += 0.15
        if agg["htf_state"] and not agg["htf_conflict"] and score:
            confidence += 0.05
        if len(df) < 200:
            confidence -= 0.10

        return ModuleResult(
            module=self.name,
            score=score,
            direction=direction_from_score(score),
            confidence=clamp(confidence, 0.0, 1.0),
            horizon_weights=self.HORIZON_WEIGHTS,
            raw=raw,
            notes=agg["notes"],
            data_quality="full" if len(df) >= 200 else "partial",
        )


def _last(s) -> float | None:
    v = s.iloc[-1] if len(s) else None
    return None if v is None or v != v else float(v)  # v != v is the NaN check
