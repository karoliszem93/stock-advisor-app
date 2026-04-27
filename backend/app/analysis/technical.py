"""Technical analysis module.

Captures classical chart-based signals on price action:
  - RSI (14)         — overbought/oversold momentum oscillator
  - MACD (12,26,9)   — trend + momentum crossover signal
  - EMAs (20/50/200) — trend regime & relative position
  - Bollinger Bands  — volatility envelope, %B position
  - ATR (14)         — volatility magnitude (for stop-sizing)
  - ADX (14)         — trend strength
  - Support/Resistance — last 90-day swing highs/lows

Score blending logic (each contributes ±0.2..0.3):
  + RSI mean-reverting buy zones (oversold in uptrend), sell zones (overbought in downtrend)
  + MACD bullish/bearish cross within last 5 bars
  + Price above 200-EMA = trend up
  + ADX > 20 amplifies the trend signal; ADX < 15 dampens
  + Bollinger %B near 0 = oversold, near 1 = overbought
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.analysis.base import ModuleResult, clamp, no_data, score_to_direction


def analyze_technical(ohlcv_bars: list[dict] | None) -> ModuleResult:
    if not ohlcv_bars or len(ohlcv_bars) < 60:
        return no_data("technical", "fewer than 60 daily bars available")

    df = _to_df(ohlcv_bars)
    closes = df["close"]

    # ---- indicators ----
    rsi_14 = _rsi(closes, 14).iloc[-1]
    macd_line, signal_line, hist = _macd(closes)
    ema_20 = closes.ewm(span=20, adjust=False).mean().iloc[-1]
    ema_50 = closes.ewm(span=50, adjust=False).mean().iloc[-1]
    ema_200 = (closes.ewm(span=200, adjust=False).mean().iloc[-1] if len(closes) >= 200 else None)

    bb_mid = closes.rolling(20).mean().iloc[-1]
    bb_std = closes.rolling(20).std().iloc[-1]
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_pct = (closes.iloc[-1] - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) else 0.5

    atr_14 = _atr(df, 14).iloc[-1]
    adx_14 = _adx(df, 14).iloc[-1]

    swings = _swings(df, lookback=90)

    last_close = closes.iloc[-1]

    features: dict[str, Any] = {
        "last_close": float(last_close),
        "rsi_14": _f(rsi_14),
        "macd": {"macd": _f(macd_line.iloc[-1]), "signal": _f(signal_line.iloc[-1]), "hist": _f(hist.iloc[-1])},
        "ema_20": _f(ema_20),
        "ema_50": _f(ema_50),
        "ema_200": _f(ema_200),
        "bb_pct": _f(bb_pct),
        "atr_14": _f(atr_14),
        "adx_14": _f(adx_14),
        "support_levels": swings["support"],
        "resistance_levels": swings["resistance"],
    }

    # ---- score ----
    s = 0.0
    notes: list[str] = []

    # Trend (price vs 200-EMA)
    if ema_200 and not pd.isna(ema_200):
        trend_strength = (last_close - ema_200) / ema_200
        s += clamp(trend_strength * 5, -0.3, 0.3)
        if trend_strength > 0.02:
            notes.append(f"Price {trend_strength*100:.1f}% above 200-EMA — trend up")
        elif trend_strength < -0.02:
            notes.append(f"Price {-trend_strength*100:.1f}% below 200-EMA — trend down")

    # Momentum (RSI buy zones in trend)
    if not pd.isna(rsi_14):
        if 30 <= rsi_14 <= 45 and last_close > (ema_50 or last_close):
            s += 0.2
            notes.append(f"RSI {rsi_14:.0f} — pullback in uptrend")
        elif 55 <= rsi_14 <= 70 and ema_200 and last_close < ema_200:
            s -= 0.2
            notes.append(f"RSI {rsi_14:.0f} — bounce in downtrend")
        elif rsi_14 < 30:
            s += 0.15
            notes.append(f"RSI {rsi_14:.0f} — oversold")
        elif rsi_14 > 75:
            s -= 0.15
            notes.append(f"RSI {rsi_14:.0f} — overbought")

    # MACD recent cross
    cross = _recent_cross(macd_line, signal_line, lookback=5)
    if cross == "bull":
        s += 0.2
        notes.append("Recent MACD bullish cross")
    elif cross == "bear":
        s -= 0.2
        notes.append("Recent MACD bearish cross")

    # Trend strength via ADX (amplifier, not standalone)
    if not pd.isna(adx_14):
        if adx_14 > 25:
            s *= 1.15
            notes.append(f"ADX {adx_14:.0f} — strong trend")
        elif adx_14 < 15:
            s *= 0.85
            notes.append(f"ADX {adx_14:.0f} — weak trend, signals less reliable")

    # Bollinger extreme (mean-reversion bias)
    if bb_pct is not None:
        if bb_pct < 0.05:
            s += 0.10
        elif bb_pct > 0.95:
            s -= 0.10

    score = clamp(s)
    confidence = 0.6  # baseline; modulated by ADX and data length
    if not pd.isna(adx_14) and adx_14 > 25:
        confidence += 0.15
    if len(closes) < 200:
        confidence -= 0.1
    confidence = clamp(confidence, 0.0, 1.0)

    return ModuleResult(
        module="technical",
        features=features,
        score=score,
        direction=score_to_direction(score),
        confidence=confidence,
        data_quality="full" if len(closes) >= 200 else "partial",
        notes=notes,
    )


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _to_df(bars: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    # use adjusted close for everything return-related; raw close for indicators
    df["close"] = df["adj_close"].fillna(df["close"])
    return df


def _f(x) -> float | None:
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    return 100 - 100 / (1 + rs)


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist


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


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    plus_dm = (high.diff()).clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    # only the dominant move counts each bar
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0)
    minus_dm = minus_dm.where(minus_dm > plus_dm.shift(0), 0)
    atr = _atr(df, period)
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)
    adx = dx.rolling(period).mean()
    return adx


def _recent_cross(line: pd.Series, signal: pd.Series, lookback: int = 5) -> str | None:
    diff = (line - signal).tail(lookback + 1)
    if len(diff) < 2:
        return None
    flips = (diff.shift(1) * diff < 0)
    if not flips.tail(lookback).any():
        return None
    last_flip_idx = flips.tail(lookback)[flips.tail(lookback)].index[-1]
    return "bull" if diff.iloc[-1] > 0 else "bear"


def _swings(df: pd.DataFrame, lookback: int = 90) -> dict:
    """Find recent significant swing highs/lows via rolling argmax/argmin."""
    recent = df.tail(lookback)
    if len(recent) < 5:
        return {"support": [], "resistance": []}
    last = float(recent["close"].iloc[-1])

    highs = recent["high"].nlargest(5).round(2).tolist()
    lows = recent["low"].nsmallest(5).round(2).tolist()

    resistance = sorted({h for h in highs if h > last}, reverse=False)[:3]
    support = sorted({l for l in lows if l < last}, reverse=True)[:3]
    return {"support": support, "resistance": resistance}
