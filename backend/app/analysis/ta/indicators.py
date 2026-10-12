"""Indicator math shared by every technical rule.

Conventions match TradingView (and the frontend's src/lib/indicators.ts):
  - RSI, ATR, ADX use Wilder's smoothing (alpha = 1/period)
  - Bollinger Bands use the population standard deviation
  - EMAs are recursive from the first value (adjust=False)

Every function takes/returns pandas Series aligned to the input index.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, period: int) -> pd.Series:
    return s.rolling(period, min_periods=period).mean()


def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False, min_periods=period).mean()


def wilder(s: pd.Series, period: int) -> pd.Series:
    """Wilder's moving average (RMA): an EMA with alpha = 1/period."""
    return s.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = wilder(delta.clip(lower=0), period)
    loss = wilder(-delta.clip(upper=0), period)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1
    ).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return wilder(true_range(df), period)


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Returns columns adx, plus_di, minus_di."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = wilder(true_range(df), period)
    plus_di = 100 * wilder(plus_dm, period) / tr
    minus_di = 100 * wilder(minus_dm, period) / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame({"adx": wilder(dx, period), "plus_di": plus_di, "minus_di": minus_di})


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bollinger(close: pd.Series, period: int = 20, mult: float = 2.0) -> pd.DataFrame:
    mid = sma(close, period)
    sd = close.rolling(period, min_periods=period).std(ddof=0)
    upper, lower = mid + mult * sd, mid - mult * sd
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower, "pct_b": pct_b})


def zscore(close: pd.Series, period: int) -> pd.Series:
    mu = sma(close, period)
    sd = close.rolling(period, min_periods=period).std(ddof=0)
    return (close - mu) / sd.replace(0, np.nan)


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def pivots(df: pd.DataFrame, width: int = 5) -> tuple[list[int], list[int]]:
    """Fractal swing points: a bar whose high (low) is the extreme of the
    `width` bars on each side. A pivot at index i is only *known* at i + width
    (callers must respect that to avoid look-ahead)."""
    highs, lows = [], []
    h, lo = df["high"].to_numpy(), df["low"].to_numpy()
    for i in range(width, len(df) - width):
        # extreme of the window; on ties the first (leftmost) bar is the pivot
        left_h, right_h = h[i - width: i], h[i + 1: i + width + 1]
        left_l, right_l = lo[i - width: i], lo[i + 1: i + width + 1]
        if h[i] > left_h.max() and h[i] >= right_h.max():
            highs.append(i)
        if lo[i] < left_l.min() and lo[i] <= right_l.min():
            lows.append(i)
    return highs, lows


def cross_up(a: pd.Series, b: pd.Series | float) -> pd.Series:
    b_prev = b.shift(1) if isinstance(b, pd.Series) else b
    return (a > b) & (a.shift(1) <= b_prev)


def cross_down(a: pd.Series, b: pd.Series | float) -> pd.Series:
    b_prev = b.shift(1) if isinstance(b, pd.Series) else b
    return (a < b) & (a.shift(1) >= b_prev)
