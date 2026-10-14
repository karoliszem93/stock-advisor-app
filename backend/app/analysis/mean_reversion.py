"""Mean-reversion module.

Detects when price is far enough from its recent mean to expect a snap-back.
Useful for short timeframes where overshoot reverses; less so on long
timeframes where extension can persist.

Uses the shared rules engine (app/analysis/ta/rules.py), the same rules the
Chart page draws:
  - Z-score: close vs 20- and 50-bar mean (stretched up = bearish), plus a
    ±0.10 flag beyond 5 ATR from the 200-EMA
  - Bollinger Bands (20, 2): %B at the lower / upper band (±0.15)

Bollinger Bands are scored here only — the technical module no longer
counts them too.
"""

from __future__ import annotations

from app.analysis.base import (
    AnalysisContext,
    BaseAnalysisModule,
    ModuleResult,
    clamp,
    direction_from_score,
    no_data,
)
from app.analysis.ta import rules as ta


class MeanReversionModule(BaseAnalysisModule):
    name = "mean_reversion"
    description = "Z-score of price vs short-term means; Bollinger stretch."

    HORIZON_WEIGHTS = {
        "1w": 1.0, "2w": 0.85, "1m": 0.55, "3m": 0.30,
        "6m": 0.15, "1y": 0.05, "3y": 0.0,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        bars = (ctx.ohlcv or {}).get("bars") if ctx.ohlcv else None
        if not bars or len(bars) < 60:
            r = no_data(self.name, "fewer than 60 daily bars")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        df = ta.build_frame(bars, "date")
        c = ta.Calc(df)
        z, bb = ta.rule_zscore(c), ta.rule_bollinger(c)
        agg = ta.aggregate_mean_reversion({"zscore": z, "bollinger": bb})
        score = clamp(agg["score"])
        pct_b = c.bb["pct_b"].iloc[-1]

        return ModuleResult(
            module=self.name,
            score=score,
            direction=direction_from_score(score),
            confidence=clamp(0.5 + (0.1 if z.meta.get("z20") is not None else 0), 0.0, 1.0),
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "z20": z.meta.get("z20"),
                "z50": z.meta.get("z50"),
                "bb_pct": None if pct_b != pct_b else float(pct_b),
                "stretch_atr": z.meta.get("stretch_atr"),
                "last_close": float(df["close"].iloc[-1]),
                "rules": {
                    r.id: {"score": round(r.score, 3), "state": r.state, "status": r.status} for r in (z, bb)
                },
            },
            notes=agg["notes"],
            data_quality="full" if len(df) >= 200 else "partial",
        )
