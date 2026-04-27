"""Mean-reversion module.

Detects when price is far enough from its recent mean to expect a snap-back.
Useful for short timeframes where overshoot reverses; less so on long
timeframes where extension can persist.

Components:
  + Z-score of close vs 20-day mean (std dev)
  + Z-score of close vs 50-day mean
  + Bollinger %B reading
  + Distance to 200-EMA in ATR units (extreme stretch flag)

Score sign convention: large *positive* z-score (price stretched up) is
bearish here (we expect mean reversion DOWN). Large *negative* z-score
is bullish (expect snap UP).
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

        df = pd.DataFrame(bars)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        closes = df["adj_close"].fillna(df["close"])

        last = float(closes.iloc[-1])
        z20 = _zscore(closes, 20)
        z50 = _zscore(closes, 50)
        bb_pct = _bb_pct(closes, 20)

        atr = _atr(df, 14).iloc[-1]
        ema_200 = (closes.ewm(span=200, adjust=False).mean().iloc[-1]
                   if len(closes) >= 200 else None)
        stretch_atr = (
            (last - ema_200) / atr if ema_200 and atr and not pd.isna(ema_200) and not pd.isna(atr) and atr != 0
            else None
        )

        s = 0.0
        notes: list[str] = []

        if z20 is not None:
            s -= clamp(z20 * 0.20, -0.30, 0.30)  # invert: stretched up → bearish
            if z20 > 1.5:
                notes.append(f"Z-score vs 20d mean = {z20:.1f} (stretched upside).")
            elif z20 < -1.5:
                notes.append(f"Z-score vs 20d mean = {z20:.1f} (stretched downside).")

        if z50 is not None:
            s -= clamp(z50 * 0.10, -0.15, 0.15)

        if bb_pct is not None:
            if bb_pct < 0.10:
                s += 0.15
                notes.append("Lower Bollinger band — oversold.")
            elif bb_pct > 0.90:
                s -= 0.15
                notes.append("Upper Bollinger band — overbought.")

        if stretch_atr is not None:
            if stretch_atr > 5:
                s -= 0.10
                notes.append(f"Price {stretch_atr:.1f} ATRs above 200-EMA — long-term stretch.")
            elif stretch_atr < -5:
                s += 0.10
                notes.append(f"Price {-stretch_atr:.1f} ATRs below 200-EMA — long-term stretch.")

        score = clamp(s)
        confidence = 0.5 + (0.1 if z20 is not None else 0)
        confidence = clamp(confidence, 0.0, 1.0)

        return ModuleResult(
            module=self.name,
            score=score,
            direction=direction_from_score(score),
            confidence=confidence,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "z20": z20,
                "z50": z50,
                "bb_pct": bb_pct,
                "stretch_atr": stretch_atr,
                "last_close": last,
            },
            notes=notes,
            data_quality="full" if len(closes) >= 200 else "partial",
        )


def _zscore(s: pd.Series, period: int) -> float | None:
    if len(s) < period:
        return None
    window = s.tail(period)
    mu = float(window.mean())
    sigma = float(window.std())
    if sigma == 0:
        return 0.0
    return float((s.iloc[-1] - mu) / sigma)


def _bb_pct(s: pd.Series, period: int) -> float | None:
    if len(s) < period:
        return None
    window = s.tail(period)
    mu = window.mean()
    sd = window.std()
    upper = mu + 2 * sd
    lower = mu - 2 * sd
    if (upper - lower) == 0:
        return 0.5
    return float((s.iloc[-1] - lower) / (upper - lower))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close_prev = df["close"].astype(float).shift(1)
    tr = pd.concat([
        (high - low),
        (high - close_prev).abs(),
        (low - close_prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()
