"""Technical-analysis rules engine — the single source of truth for chart rules.

Each rule looks at an OHLCV frame and returns:
  - score / state / status at the LATEST bar  -> used by the scoring modules
  - events: historical buy/sell signals          -> drawn on the chart
  - overlays: lines, panes, levels, pattern outlines -> drawn on the chart

The daily pipeline (technical / mean_reversion modules) and the Chart page
both call `evaluate()`, so what you inspect by hand is exactly what the
system scored.

No look-ahead: an event at bar i only uses data up to bar i. Swing pivots
need `PIVOT_WIDTH` bars on each side, so a pivot at bar p is first usable
at bar p + PIVOT_WIDTH; higher-timeframe bars are used only once complete.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.analysis.ta import indicators as ind

PIVOT_WIDTH = 5
SR_LOOKBACK = 120
RECENT_BARS = 5

# rule id -> scoring module (what the chart panel groups by)
TECHNICAL_RULES = (
    "trend_ema200", "rsi", "macd", "adx", "breakout", "obv", "unusual_volume",
    "support_resistance", "candles", "chart_patterns", "htf_trend",
)
MEAN_REVERSION_RULES = ("bollinger", "zscore")
MOMENTUM_RULES = ("relative_strength",)


@dataclass
class RuleOutput:
    id: str
    name: str
    category: str
    module: str
    description: str
    score: float = 0.0
    state: int = 0           # -1 bearish, 0 neutral, +1 bullish (latest bar)
    status: str = ""         # plain-language reading of the latest bar
    events: list[dict] = field(default_factory=list)    # {"i", "side", "label"}
    overlays: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    available: bool = True


# ---------------------------------------------------------------------------
# frame + precomputed indicators
# ---------------------------------------------------------------------------
def build_frame(bars: list[dict], time_key: str = "date") -> pd.DataFrame:
    """bars -> DataFrame[open, high, low, close, volume, time, ts] with a RangeIndex."""
    df = pd.DataFrame(bars)
    df = df.rename(columns={time_key: "time"})
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    df["volume"] = df["volume"].fillna(0)
    df[["open", "high", "low"]] = df[["open", "high", "low"]].apply(lambda s: s.fillna(df["close"]))
    t = df["time"]
    df["ts"] = pd.to_datetime(t, unit="s", utc=True) if pd.api.types.is_numeric_dtype(t) else pd.to_datetime(t)
    return df


class _Calc:
    """Indicators computed once and shared by all rules."""

    def __init__(self, df: pd.DataFrame):
        c = df["close"]
        self.df = df
        self.n = len(df)
        self.close = c
        self.ema20 = ind.ema(c, 20)
        self.ema50 = ind.ema(c, 50)
        self.ema200 = ind.ema(c, 200)
        self.rsi = ind.rsi(c, 14)
        self.macd = ind.macd(c)
        self.atr = ind.atr(df, 14)
        self.adx = ind.adx(df, 14)
        self.bb = ind.bollinger(c, 20, 2.0)
        self.z20 = ind.zscore(c, 20)
        self.z50 = ind.zscore(c, 50)
        self.has_volume = bool((df["volume"] > 0).sum() > 0.8 * self.n)
        self.vol_avg_prev = df["volume"].rolling(20, min_periods=20).mean().shift(1)
        self.obv = ind.obv(df)
        self.pivot_highs, self.pivot_lows = ind.pivots(df, PIVOT_WIDTH)
        # numpy views for per-bar loops (pandas scalar access is slow)
        self.h, self.lo = df["high"].to_numpy(float), df["low"].to_numpy(float)
        self.o, self.cl = df["open"].to_numpy(float), c.to_numpy(float)
        self.atr_np = self.atr.to_numpy(float)


def _last(s: pd.Series) -> float | None:
    v = s.iloc[-1] if len(s) else None
    return None if v is None or pd.isna(v) else float(v)


def _events(mask: pd.Series, side: str, label: str) -> list[dict]:
    return [{"i": int(i), "side": side, "label": label} for i in np.flatnonzero(mask.fillna(False).to_numpy())]


def _debounce(mask: pd.Series, bars: int) -> pd.Series:
    """Keep a True only if there was no True in the previous `bars` bars."""
    arr = mask.fillna(False).to_numpy()
    out = np.zeros_like(arr)
    last = -10**9
    for i, v in enumerate(arr):
        if v and i - last > bars:
            out[i] = True
            last = i
    return pd.Series(out, index=mask.index)


def _recent(events: list[dict], n_bars: int, last_i: int, side: str | None = None) -> dict | None:
    """Most recent event within the last `n_bars` bars (optionally of one side)."""
    for e in reversed(events):
        if e["i"] < last_i - n_bars + 1:
            return None
        if side is None or e["side"] == side:
            return e
    return None


def _line(values: pd.Series, name: str, color: str, pane: str = "main", **kw) -> dict:
    return {"type": "line", "pane": pane, "name": name, "color": color, "values": values, **kw}


def _ago(i: int, last_i: int) -> str:
    d = last_i - i
    return "on the last bar" if d == 0 else f"{d} bar{'s' if d != 1 else ''} ago"


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------
def rule_trend_ema200(c: _Calc) -> RuleOutput:
    r = RuleOutput("trend_ema200", "Trend: price vs 200-EMA", "Trend", "technical",
                   "Above the 200-period EMA = long-term uptrend. Score scales with the distance "
                   "(±0.30 max). Signals mark crosses of the EMA.")
    r.events = _events(ind.cross_up(c.close, c.ema200), "buy", "200 EMA ↑") + \
        _events(ind.cross_down(c.close, c.ema200), "sell", "200 EMA ↓")
    r.overlays = [_line(c.ema200, "EMA 200", "#e879f9", width=2), _line(c.ema50, "EMA 50", "#3b82f6", style="dashed")]
    e200, close = _last(c.ema200), _last(c.close)
    if e200 is None:
        r.status, r.available = "Needs 200 bars of history.", False
        return r
    dist = (close - e200) / e200
    r.score = float(np.clip(dist * 5, -0.3, 0.3))
    r.state = 1 if dist > 0.02 else -1 if dist < -0.02 else 0
    r.status = f"Price {abs(dist) * 100:.1f}% {'above' if dist >= 0 else 'below'} the 200-EMA — " + \
        ("uptrend." if r.state > 0 else "downtrend." if r.state < 0 else "hugging it, no clear trend.")
    return r


def rule_rsi(c: _Calc) -> RuleOutput:
    r = RuleOutput("rsi", "RSI (14) zones", "Momentum", "technical",
                   "Buy: RSI 30–45 in an uptrend (pullback, +0.20) or below 30 (oversold, +0.15). "
                   "Sell: RSI 55–70 in a downtrend (bounce, −0.20) or above 75 (overbought, −0.15). "
                   "Signals: RSI leaving oversold/overbought, and pullbacks/bounces ending.")
    rsi, close = c.rsi, c.close
    up, down = close > c.ema200, close < c.ema200
    pullback_end = ind.cross_up(rsi, 45) & up & (rsi.rolling(5).min().shift(1) < 42)
    bounce_end = ind.cross_down(rsi, 55) & down & (rsi.rolling(5).max().shift(1) > 58)
    r.events = sorted(
        _events(ind.cross_up(rsi, 30), "buy", "RSI 30 ↑") + _events(pullback_end, "buy", "RSI pullback")
        + _events(ind.cross_down(rsi, 70), "sell", "RSI 70 ↓") + _events(bounce_end, "sell", "RSI bounce"),
        key=lambda e: e["i"],
    )
    r.overlays = [_line(rsi, "RSI 14", "#c084fc", pane="rsi", guides=[70, 55, 45, 30])]
    v, e50, e200 = _last(rsi), _last(c.ema50), _last(c.ema200)
    close_l = _last(close)
    if v is None:
        r.status, r.available = "Not enough bars.", False
        return r
    if 30 <= v <= 45 and close_l > (e50 or close_l):
        r.score, r.state, r.status = 0.20, 1, f"RSI {v:.0f} — pullback within an uptrend."
    elif 55 <= v <= 70 and e200 and close_l < e200:
        r.score, r.state, r.status = -0.20, -1, f"RSI {v:.0f} — bounce within a downtrend."
    elif v < 30:
        r.score, r.state, r.status = 0.15, 1, f"RSI {v:.0f} — oversold."
    elif v > 75:
        r.score, r.state, r.status = -0.15, -1, f"RSI {v:.0f} — overbought."
    else:
        r.status = f"RSI {v:.0f} — no signal zone."
    return r


def rule_macd(c: _Calc) -> RuleOutput:
    r = RuleOutput("macd", "MACD (12, 26, 9) crossover", "Momentum", "technical",
                   "MACD line crossing above its signal line = bullish, below = bearish. "
                   f"Scores ±0.20 while the cross is within the last {RECENT_BARS} bars.")
    m = c.macd
    r.events = sorted(_events(ind.cross_up(m["macd"], m["signal"]), "buy", "MACD ↑")
                      + _events(ind.cross_down(m["macd"], m["signal"]), "sell", "MACD ↓"), key=lambda e: e["i"])
    r.overlays = [
        {"type": "histogram", "pane": "macd", "name": "MACD hist", "values": m["hist"],
         "colors": ["rgba(38,166,154,0.6)" if v >= 0 else "rgba(239,83,80,0.6)" for v in m["hist"].fillna(0)]},
        _line(m["macd"], "MACD", "#60a5fa", pane="macd"),
        _line(m["signal"], "Signal", "#f59e0b", pane="macd"),
    ]
    hist = _last(m["hist"])
    if hist is None:
        r.status, r.available = "Not enough bars.", False
        return r
    last_i = c.n - 1
    rec = _recent(r.events, RECENT_BARS, last_i)
    r.state = 1 if hist > 0 else -1
    if rec:
        r.score = 0.20 if rec["side"] == "buy" else -0.20
        r.status = f"{'Bullish' if rec['side'] == 'buy' else 'Bearish'} MACD cross {_ago(rec['i'], last_i)}."
    else:
        r.status = f"MACD {'above' if hist > 0 else 'below'} signal — no recent cross."
    return r


def rule_adx(c: _Calc) -> RuleOutput:
    r = RuleOutput("adx", "ADX (14) trend strength", "Trend", "technical",
                   "ADX > 25 = strong trend: all technical signals ×1.15; ADX < 15 = no trend: ×0.85. "
                   f"Signals: +DI/−DI crosses while ADX > 20 (±0.10 within {RECENT_BARS} bars).")
    a = c.adx
    strong = a["adx"] > 20
    r.events = sorted(_events(ind.cross_up(a["plus_di"], a["minus_di"]) & strong, "buy", "DI+ ↑")
                      + _events(ind.cross_down(a["plus_di"], a["minus_di"]) & strong, "sell", "DI− ↑"),
                      key=lambda e: e["i"])
    r.overlays = [
        _line(a["adx"], "ADX", "#e5e7eb", pane="adx", guides=[25]),
        _line(a["plus_di"], "+DI", "#26a69a", pane="adx"),
        _line(a["minus_di"], "−DI", "#ef5350", pane="adx"),
    ]
    v, p, m = _last(a["adx"]), _last(a["plus_di"]), _last(a["minus_di"])
    if v is None:
        r.status, r.available = "Not enough bars.", False
        r.meta["amplifier"] = 1.0
        return r
    r.meta["amplifier"] = 1.15 if v > 25 else 0.85 if v < 15 else 1.0
    r.meta["adx"] = v
    last_i = c.n - 1
    rec = _recent(r.events, RECENT_BARS, last_i)
    if rec:
        r.score = 0.10 if rec["side"] == "buy" else -0.10
    r.state = (1 if p > m else -1) if v > 20 else 0
    strength = "strong trend" if v > 25 else "weak / no trend" if v < 15 else "moderate trend"
    r.status = f"ADX {v:.0f} — {strength}; {'+DI above −DI (buyers)' if p > m else '−DI above +DI (sellers)'}." + \
        (f" DI cross {_ago(rec['i'], last_i)}." if rec else "")
    return r


def rule_breakout(c: _Calc) -> RuleOutput:
    r = RuleOutput("breakout", "Breakout with volume", "Volume", "technical",
                   "Close above the prior 20-bar high (below the 20-bar low) on volume ≥ 1.5× the 20-bar "
                   f"average. Unconfirmed (low-volume) breakouts are ignored. ±0.20 within {RECENT_BARS} bars.")
    df = c.df
    hh = df["high"].rolling(20, min_periods=20).max().shift(1)
    ll = df["low"].rolling(20, min_periods=20).min().shift(1)
    r.overlays = [_line(hh, "20-bar high", "#6b7280", style="dotted"), _line(ll, "20-bar low", "#6b7280", style="dotted")]
    if not c.has_volume:
        r.status, r.available = "No volume data for this symbol.", False
        return r
    vol_ok = df["volume"] >= 1.5 * c.vol_avg_prev
    first_up = (df["close"] > hh) & (df["close"].shift(1) <= hh.shift(1))
    first_dn = (df["close"] < ll) & (df["close"].shift(1) >= ll.shift(1))
    r.events = sorted(_events(first_up & vol_ok, "buy", "Breakout") + _events(first_dn & vol_ok, "sell", "Breakdown"),
                      key=lambda e: e["i"])
    last_i = c.n - 1
    rec = _recent(r.events, RECENT_BARS, last_i)
    if rec:
        ratio = df["volume"].iloc[rec["i"]] / c.vol_avg_prev.iloc[rec["i"]]
        r.score = 0.20 if rec["side"] == "buy" else -0.20
        r.state = 1 if rec["side"] == "buy" else -1
        r.status = f"Volume-confirmed {'breakout above the 20-bar high' if rec['side'] == 'buy' else 'breakdown below the 20-bar low'} " \
                   f"{_ago(rec['i'], last_i)} ({ratio:.1f}× average volume)."
    else:
        r.status = f"Inside its 20-bar range ({_last(ll):.2f} – {_last(hh):.2f})." if _last(hh) else "Not enough bars."
    return r


def rule_obv(c: _Calc) -> RuleOutput:
    r = RuleOutput("obv", "On-balance volume", "Volume", "technical",
                   "Divergence: price at a 20-bar low while OBV is not (accumulation, buy) or price at a 20-bar "
                   "high while OBV is not (distribution, sell), ±0.15 within 5 bars. OBV trend agreeing with "
                   "price adds ±0.05.")
    if not c.has_volume:
        r.status, r.available = "No volume data for this symbol.", False
        return r
    o, close = c.obv, c.close
    o_ema = ind.ema(o, 20)
    # price makes a 20-bar extreme while OBV is not only off its own extreme but
    # trending the other way (below / above its 20-EMA)
    bull = (close <= close.rolling(20).min()) & (o > o.rolling(20).min().shift(1)) & (o > o_ema)
    bear = (close >= close.rolling(20).max()) & (o < o.rolling(20).max().shift(1)) & (o < o_ema)
    r.events = sorted(_events(_debounce(bull, 10), "buy", "OBV divergence")
                      + _events(_debounce(bear, 10), "sell", "OBV divergence"), key=lambda e: e["i"])
    r.overlays = [_line(o, "OBV", "#22d3ee", pane="obv"), _line(o_ema, "OBV EMA 20", "#f59e0b", pane="obv")]
    last_i = c.n - 1
    rec = _recent(r.events, RECENT_BARS, last_i)
    obv_slope = (o_ema - o_ema.shift(10)).iloc[-1]
    px_slope = (c.ema20 - c.ema20.shift(10)).iloc[-1]
    parts = []
    if rec:
        r.score += 0.15 if rec["side"] == "buy" else -0.15
        parts.append(f"{'Bullish' if rec['side'] == 'buy' else 'Bearish'} OBV divergence {_ago(rec['i'], last_i)}.")
    if not pd.isna(obv_slope) and not pd.isna(px_slope) and np.sign(obv_slope) == np.sign(px_slope) and obv_slope != 0:
        r.score += 0.05 * np.sign(obv_slope)
        parts.append(f"OBV {'rising' if obv_slope > 0 else 'falling'} with price — volume confirms the move.")
    elif not pd.isna(obv_slope):
        parts.append(f"OBV {'rising' if obv_slope > 0 else 'falling'} against the price trend.")
    r.state = int(np.sign(r.score))
    r.status = " ".join(parts) or "No OBV signal."
    return r


def rule_unusual_volume(c: _Calc) -> RuleOutput:
    r = RuleOutput("unusual_volume", "Unusual volume", "Volume", "technical",
                   "Volume ≥ 2.5× its 20-bar average. Up-candle = buying pressure, down-candle = selling. "
                   "±0.05 within 3 bars.")
    df = c.df
    if not c.has_volume:
        r.status, r.available = "No volume data for this symbol.", False
        return r
    ratio = df["volume"] / c.vol_avg_prev
    spike = ratio >= 2.5
    up = df["close"] >= df["open"]
    r.events = sorted(
        [{"i": e["i"], "side": "buy", "label": f"Vol {ratio.iloc[e['i']]:.1f}×"} for e in _events(spike & up, "buy", "")]
        + [{"i": e["i"], "side": "sell", "label": f"Vol {ratio.iloc[e['i']]:.1f}×"} for e in _events(spike & ~up, "sell", "")],
        key=lambda e: e["i"],
    )
    colors = [
        ("#26a69a" if u else "#ef5350") if s else ("rgba(38,166,154,0.35)" if u else "rgba(239,83,80,0.35)")
        for s, u in zip(spike.fillna(False), up, strict=False)
    ]
    r.overlays = [
        {"type": "histogram", "pane": "volume", "name": "Volume", "values": df["volume"], "colors": colors},
        _line(df["volume"].rolling(20).mean(), "Avg volume 20", "#f59e0b", pane="volume"),
    ]
    last_i = c.n - 1
    rec = _recent(r.events, 3, last_i)
    if rec:
        r.score = 0.05 if rec["side"] == "buy" else -0.05
        r.state = int(np.sign(r.score))
        r.status = f"Volume spike {rec['label'].split()[-1]} on a {'rising' if rec['side'] == 'buy' else 'falling'} bar {_ago(rec['i'], last_i)}."
    else:
        last_ratio = _last(ratio)
        r.status = f"Volume {last_ratio:.1f}× average — normal." if last_ratio else "Normal volume."
    return r


def _cluster_levels(prices: list[float], tol: float) -> list[tuple[float, int]]:
    """Merge nearby pivot prices into (level, touches)."""
    if not prices:
        return []
    prices = sorted(prices)
    groups = [[prices[0]]]
    for p in prices[1:]:
        if p - groups[-1][-1] <= tol:
            groups[-1].append(p)
        else:
            groups.append([p])
    return [(float(np.mean(g)), len(g)) for g in groups]


def _levels_at(c: _Calc, i: int) -> tuple[list[tuple[float, int]], list[tuple[float, int]]]:
    """Support / resistance as known at bar i (pivots confirmed by then, last SR_LOOKBACK bars)."""
    atr = c.atr_np[i]
    if not np.isfinite(atr) or atr <= 0:
        return [], []
    lo_i, hi_i = i - SR_LOOKBACK, i - PIVOT_WIDTH
    hs = c.pivot_highs[bisect.bisect_left(c.pivot_highs, lo_i): bisect.bisect_right(c.pivot_highs, hi_i)]
    ls = c.pivot_lows[bisect.bisect_left(c.pivot_lows, lo_i): bisect.bisect_right(c.pivot_lows, hi_i)]
    prices = [float(c.h[p]) for p in hs] + [float(c.lo[p]) for p in ls]
    levels = _cluster_levels(prices, 0.6 * float(atr))
    close = float(c.cl[i])
    support = sorted([lv for lv in levels if lv[0] < close], key=lambda lv: -lv[0])
    resistance = sorted([lv for lv in levels if lv[0] > close], key=lambda lv: lv[0])
    return support, resistance


def rule_support_resistance(c: _Calc) -> RuleOutput:
    r = RuleOutput("support_resistance", "Support & resistance", "Price levels", "technical",
                   f"Levels from swing highs/lows of the last {SR_LOOKBACK} bars (nearby swings merged; "
                   "touches = strength). Buy: bullish bounce off support; sell: rejection at resistance "
                   "(±0.15 within 3 bars). Within 1 ATR of support +0.05 / of resistance −0.05. "
                   "Also used to place stops and targets.")
    start = max(SR_LOOKBACK // 2, 30)
    bounces, rejects = [], []
    for i in range(start, c.n):
        sup, res = _levels_at(c, i)
        atr = c.atr_np[i]
        o, h, lo, cl = c.o[i], c.h[i], c.lo[i], c.cl[i]
        if sup:
            s = sup[0][0]
            if lo <= s + 0.3 * atr and cl > s and cl > o:
                bounces.append(i)
        if res:
            rv = res[0][0]
            if h >= rv - 0.3 * atr and cl < rv and cl < o:
                rejects.append(i)
    deb = lambda idx: [i for k, i in enumerate(idx) if k == 0 or i - idx[k - 1] > 5]  # noqa: E731
    r.events = sorted([{"i": i, "side": "buy", "label": "Support bounce"} for i in deb(bounces)]
                      + [{"i": i, "side": "sell", "label": "Resistance reject"} for i in deb(rejects)],
                      key=lambda e: e["i"])
    last_i = c.n - 1
    sup, res = _levels_at(c, last_i)
    r.meta["support"] = [{"price": p, "touches": t} for p, t in sup[:3]]
    r.meta["resistance"] = [{"price": p, "touches": t} for p, t in res[:3]]
    r.overlays = [{"type": "levels", "levels":
                   [{"price": p, "label": f"S{k + 1} ({t}×)", "color": "#26a69a"} for k, (p, t) in enumerate(sup[:3])]
                   + [{"price": p, "label": f"R{k + 1} ({t}×)", "color": "#ef5350"} for k, (p, t) in enumerate(res[:3])]}]
    atr, close = _last(c.atr), _last(c.close)
    if atr is None or (not sup and not res):
        r.status, r.available = "Not enough swing points yet.", bool(sup or res)
        return r
    parts = []
    rec = _recent(r.events, 3, last_i)
    if rec:
        r.score += 0.15 if rec["side"] == "buy" else -0.15
        parts.append(f"{rec['label']} {_ago(rec['i'], last_i)}.")
    if sup and (close - sup[0][0]) / atr <= 1:
        r.score += 0.05
        parts.append(f"Just above support {sup[0][0]:.2f} — tight stop possible.")
    if res and (res[0][0] - close) / atr <= 1:
        r.score -= 0.05
        parts.append(f"Just below resistance {res[0][0]:.2f} — limited room.")
    if not parts:
        parts.append(f"Between support {sup[0][0]:.2f} and resistance {res[0][0]:.2f}." if sup and res
                     else f"Nearest {'support' if sup else 'resistance'} {(sup or res)[0][0]:.2f}.")
    r.state = int(np.sign(r.score))
    r.status = " ".join(parts)
    return r


def rule_candles(c: _Calc) -> RuleOutput:
    r = RuleOutput("candles", "Candlestick patterns", "Patterns", "technical",
                   "After a decline: bullish engulfing, morning star (+0.10), hammer (+0.07). After an advance: "
                   "bearish engulfing, evening star (−0.10), shooting star (−0.07). Counted within 2 bars; "
                   "candles smaller than half an ATR are ignored.")
    df = c.df
    o, h, lo, cl = df["open"], df["high"], df["low"], df["close"]
    body = (cl - o).abs()
    rng = (h - lo).replace(0, np.nan)
    upper = h - np.maximum(o, cl)
    lower = np.minimum(o, cl) - lo
    big_enough = rng >= 0.5 * c.atr
    down_ctx = (cl.shift(1) < c.ema20.shift(1)) | (cl.shift(1) < cl.shift(4))
    up_ctx = (cl.shift(1) > c.ema20.shift(1)) | (cl.shift(1) > cl.shift(4))
    green, red = cl > o, cl < o
    down_ctx = down_ctx.fillna(False)
    up_ctx = up_ctx.fillna(False)
    red1, green1 = red.shift(1, fill_value=False), green.shift(1, fill_value=False)
    red2, green2 = red.shift(2, fill_value=False), green.shift(2, fill_value=False)
    bull_engulf = red1 & green & (o <= cl.shift(1)) & (cl >= o.shift(1)) & (body > body.shift(1)) & down_ctx
    bear_engulf = green1 & red & (o >= cl.shift(1)) & (cl <= o.shift(1)) & (body > body.shift(1)) & up_ctx
    hammer = (body <= 0.35 * rng) & (lower >= 2 * body) & (upper <= 0.15 * rng) & down_ctx & big_enough
    star = (body <= 0.35 * rng) & (upper >= 2 * body) & (lower <= 0.15 * rng) & up_ctx & big_enough
    b2, mid2 = body.shift(2), (o.shift(2) + cl.shift(2)) / 2
    morning = red2 & (b2 >= 0.6 * rng.shift(2)) & (body.shift(1) <= 0.3 * b2) & green & (cl > mid2) \
        & down_ctx.shift(1, fill_value=False)
    evening = green2 & (b2 >= 0.6 * rng.shift(2)) & (body.shift(1) <= 0.3 * b2) & red & (cl < mid2) \
        & up_ctx.shift(1, fill_value=False)
    patterns = [
        (bull_engulf & big_enough, "buy", "Bullish engulfing", 0.10),
        (morning, "buy", "Morning star", 0.10),
        (hammer, "buy", "Hammer", 0.07),
        (bear_engulf & big_enough, "sell", "Bearish engulfing", 0.10),
        (evening, "sell", "Evening star", 0.10),
        (star, "sell", "Shooting star", 0.07),
    ]
    events = []
    weight = {}
    for mask, side, label, w in patterns:
        events += _events(mask.astype(bool), side, label)
        weight[label] = w
    r.events = sorted(events, key=lambda e: e["i"])
    last_i = c.n - 1
    recent = [e for e in r.events if e["i"] >= last_i - 1]
    if recent:
        best = max(recent, key=lambda e: weight[e["label"]])
        r.score = weight[best["label"]] * (1 if best["side"] == "buy" else -1)
        r.state = int(np.sign(r.score))
        r.status = f"{best['label']} {_ago(best['i'], last_i)}."
    else:
        r.status = "No reversal candle in the last 2 bars."
    return r


def rule_chart_patterns(c: _Calc) -> RuleOutput:
    r = RuleOutput("chart_patterns", "Chart patterns", "Patterns", "technical",
                   "Double bottom / top (two swings within 0.6 ATR, 10–60 bars apart, confirmed on a close "
                   "through the neckline) and bull / bear flags (≥4 ATR pole within 10 bars, tight ≤50% "
                   f"pullback on lighter volume, confirmed on breakout). ±0.20 within {RECENT_BARS} bars.")
    df = c.df
    h, lo, cl, vol = (df[k].to_numpy() for k in ("high", "low", "close", "volume"))
    atr = c.atr.to_numpy()
    events, segments = [], []

    def double(pivots_idx: list[int], kind: str):
        for k, b in enumerate(pivots_idx):
            for a in (pivots_idx[q] for q in range(k - 1, -1, -1)):
                if b - a > 60:
                    break
                if b - a < 10 or np.isnan(atr[b]):
                    continue
                pa, pb = (lo[a], lo[b]) if kind == "bottom" else (h[a], h[b])
                if abs(pa - pb) > 0.6 * atr[b]:
                    continue
                mid_i = a + (int(np.argmax(h[a:b + 1])) if kind == "bottom" else int(np.argmin(lo[a:b + 1])))
                neck = h[mid_i] if kind == "bottom" else lo[mid_i]
                depth = neck - max(pa, pb) if kind == "bottom" else min(pa, pb) - neck
                if depth < 2 * atr[b]:
                    continue
                extreme = min(pa, pb) if kind == "bottom" else max(pa, pb)
                for j in range(b + PIVOT_WIDTH, min(b + 40, len(cl))):
                    if (kind == "bottom" and cl[j] < extreme - 0.5 * atr[b]) or \
                       (kind == "top" and cl[j] > extreme + 0.5 * atr[b]):
                        break  # pattern failed before confirming
                    if (kind == "bottom" and cl[j] > neck) or (kind == "top" and cl[j] < neck):
                        side = "buy" if kind == "bottom" else "sell"
                        events.append({"i": j, "side": side, "label": f"Double {kind}"})
                        color = "#26a69a" if side == "buy" else "#ef5350"
                        segments.append({"points": [(a, pa), (mid_i, neck), (b, pb), (j, cl[j])], "color": color,
                                         "label": f"Double {kind}"})
                        segments.append({"points": [(mid_i, neck), (j, neck)], "color": color, "dashed": True})
                        break
                break  # only pair each swing with its nearest valid partner

    double(c.pivot_lows, "bottom")
    double(c.pivot_highs, "top")

    # flags
    last_flag = -100
    for j in range(30, len(cl)):
        if j - last_flag <= 10 or np.isnan(atr[j]):
            continue
        for bull in (True, False):
            seg = slice(j - 25, j - 4)
            pe = (j - 25) + int(np.argmax(h[seg]) if bull else np.argmin(lo[seg]))
            ps_seg = slice(max(pe - 10, 0), pe + 1)
            ps = max(pe - 10, 0) + int(np.argmin(lo[ps_seg]) if bull else np.argmax(h[ps_seg]))
            pole = (h[pe] - lo[ps]) if bull else (h[ps] - lo[pe])
            if pe - ps < 2 or pole < 4 * atr[pe] or j - pe < 4 or j - pe > 15:
                continue
            fh, fl = h[pe + 1:j].max(), lo[pe + 1:j].min()
            if bull:
                ok = fh <= h[pe] * 1.002 and fl >= h[pe] - 0.5 * pole and cl[j] > fh and cl[j - 1] <= fh
            else:
                ok = fl >= lo[pe] * 0.998 and fh <= lo[pe] + 0.5 * pole and cl[j] < fl and cl[j - 1] >= fl
            if ok and vol[pe + 1:j].mean() > 0 and vol[ps:pe + 1].mean() > 0:
                ok = vol[pe + 1:j].mean() < vol[ps:pe + 1].mean()
            if ok:
                side = "buy" if bull else "sell"
                events.append({"i": j, "side": side, "label": "Bull flag" if bull else "Bear flag"})
                color = "#26a69a" if bull else "#ef5350"
                top, bottom = (fh, fl)
                segments.append({"points": [(ps, lo[ps] if bull else h[ps]), (pe, h[pe] if bull else lo[pe])],
                                 "color": color, "label": "Bull flag" if bull else "Bear flag"})
                segments.append({"points": [(pe + 1, top), (j, top)], "color": color, "dashed": True})
                segments.append({"points": [(pe + 1, bottom), (j, bottom)], "color": color, "dashed": True})
                last_flag = j
                break

    r.events = sorted(events, key=lambda e: e["i"])
    r.overlays = [{"type": "segments", "segments": segments}]
    last_i = c.n - 1
    rec = _recent(r.events, RECENT_BARS, last_i)
    if rec:
        r.score = 0.20 if rec["side"] == "buy" else -0.20
        r.state = int(np.sign(r.score))
        r.status = f"{rec['label']} confirmed {_ago(rec['i'], last_i)}."
    else:
        prev = r.events[-1] if r.events else None
        r.status = "No pattern confirmed recently." + (f" Last: {prev['label']} {_ago(prev['i'], last_i)}." if prev else "")
    return r


def rule_htf_trend(c: _Calc, htf_rule: str | None, htf_label: str) -> RuleOutput:
    r = RuleOutput("htf_trend", f"{htf_label} trend", "Multi-timeframe", "technical",
                   f"{htf_label} close vs its EMA and {htf_label.lower()} MACD histogram: both up = bullish (+0.10), "
                   f"both down = bearish (−0.10). Daily signals that fight the {htf_label.lower()} trend are "
                   "damped ×0.6. Only completed bars are used.")
    if not htf_rule:
        r.status, r.available = "No higher timeframe for this interval.", False
        return r
    df = c.df.set_index("ts")
    htf = df.resample(htf_rule, label="right", closed="right").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    period = 40 if htf_rule.startswith("W") else 20
    if len(htf) < period + 10:
        r.status, r.available = f"Not enough {htf_label.lower()} bars.", False
        return r
    he = ind.ema(htf["close"], period)
    hh = ind.macd(htf["close"])["hist"]
    state = pd.Series(np.where((htf["close"] > he) & (hh > 0), 1, np.where((htf["close"] < he) & (hh < 0), -1, 0)),
                      index=htf.index).where(he.notna() & hh.notna(), 0)
    # a higher-TF bar's state applies only after it has closed (strictly later base bars)
    base = pd.DataFrame({"ts": c.df["ts"]})
    st = pd.DataFrame({"htf_ts": state.index, "state": state.to_numpy()})
    merged = pd.merge_asof(base.sort_values("ts"), st.sort_values("htf_ts"), left_on="ts", right_on="htf_ts",
                           direction="backward", allow_exact_matches=False)
    s = merged["state"].fillna(0).astype(int).reset_index(drop=True)
    change = s.ne(s.shift(1)) & s.shift(1).notna()
    r.events = sorted(_events(change & (s == 1), "buy", f"{htf_label} up") + _events(change & (s == -1), "sell", f"{htf_label} down"),
                      key=lambda e: e["i"])
    r.overlays = [{"type": "background", "values": s}]
    r.state = int(s.iloc[-1])
    r.score = 0.10 * r.state
    r.meta["htf_state"] = r.state
    r.status = {1: f"{htf_label} trend up (close above EMA {period}, MACD rising).",
                -1: f"{htf_label} trend down (close below EMA {period}, MACD falling).",
                0: f"{htf_label} trend mixed — no filter applied."}[r.state]
    return r


def rule_relative_strength(c: _Calc, benchmark: pd.Series | None, name: str | None) -> RuleOutput:
    label = name or "benchmark"
    r = RuleOutput("relative_strength", f"Relative strength vs {label}", "Relative strength", "momentum",
                   f"Price ÷ {label}, rebased to 100. Above its 50-bar average = outperforming. Signals mark "
                   "crosses. Scored in the Momentum module: 3-month outperformance ×1.5, capped ±0.20.")
    if benchmark is None or benchmark.notna().sum() < 60:
        r.status, r.available = ("Not applicable (bonds / commodities)." if name is None else "Not enough benchmark data."), False
        return r
    rs = c.close / benchmark
    first = rs.first_valid_index()
    rs_n = rs / rs.loc[first] * 100
    rs_sma = ind.sma(rs_n, 50)
    r.events = sorted(_events(_debounce(ind.cross_up(rs_n, rs_sma), 10), "buy", "RS ↑")
                      + _events(_debounce(ind.cross_down(rs_n, rs_sma), 10), "sell", "RS ↓"), key=lambda e: e["i"])
    r.overlays = [_line(rs_n, f"RS vs {label}", "#a3e635", pane="rs"),
                  _line(rs_sma, "RS 50-avg", "#9ca3af", pane="rs", style="dashed")]
    v, m = _last(rs_n), _last(rs_sma)
    rs3 = (rs.iloc[-1] / rs.iloc[-64] - 1) if len(rs) > 64 and not pd.isna(rs.iloc[-64]) else None
    if rs3 is not None:
        r.score = float(np.clip(rs3 * 1.5, -0.2, 0.2))
    r.state = (1 if v > m else -1) if v is not None and m is not None else 0
    r.status = (f"{'Outperforming' if r.state > 0 else 'Underperforming'} {label} (RS {'above' if r.state > 0 else 'below'} its 50-bar average)"
                + (f"; {rs3 * 100:+.1f}% vs {label} over ~3 months." if rs3 is not None else "."))
    return r


def rule_bollinger(c: _Calc) -> RuleOutput:
    r = RuleOutput("bollinger", "Bollinger Bands (20, 2)", "Mean reversion", "mean_reversion",
                   "%B below 0.10 (at the lower band) = stretched down, +0.15; above 0.90 = stretched up, −0.15. "
                   "Signals: price closing back inside the bands.")
    bb, close = c.bb, c.close
    r.events = sorted(_events(ind.cross_up(close, bb["lower"]), "buy", "Back inside BB")
                      + _events(ind.cross_down(close, bb["upper"]), "sell", "Back inside BB"), key=lambda e: e["i"])
    band = "rgba(167,139,250,0.8)"
    r.overlays = [_line(bb["upper"], "BB upper", band), _line(bb["lower"], "BB lower", band),
                  _line(bb["mid"], "BB mid", band, style="dashed")]
    p = _last(bb["pct_b"])
    if p is None:
        r.status, r.available = "Not enough bars.", False
        return r
    if p < 0.10:
        r.score, r.state, r.status = 0.15, 1, f"%B {p:.2f} — at the lower band, stretched down."
    elif p > 0.90:
        r.score, r.state, r.status = -0.15, -1, f"%B {p:.2f} — at the upper band, stretched up."
    else:
        r.status = f"%B {p:.2f} — inside the bands."
    return r


def rule_zscore(c: _Calc) -> RuleOutput:
    r = RuleOutput("zscore", "Z-score stretch", "Mean reversion", "mean_reversion",
                   "Distance from the 20- and 50-bar mean in standard deviations: stretched up is bearish, "
                   "stretched down bullish (−0.20×z20, −0.10×z50). More than 5 ATR from the 200-EMA ±0.10. "
                   "Signals: z20 returning inside ±2.")
    z20, z50 = c.z20, c.z50
    r.events = sorted(_events(ind.cross_up(z20, -2), "buy", "Z back > −2") + _events(ind.cross_down(z20, 2), "sell", "Z back < +2"),
                      key=lambda e: e["i"])
    r.overlays = [_line(z20, "Z-score 20", "#fbbf24", pane="z", guides=[2, 0, -2])]
    a, b = _last(z20), _last(z50)
    if a is None:
        r.status, r.available = "Not enough bars.", False
        return r
    s = -float(np.clip(a * 0.20, -0.30, 0.30))
    if b is not None:
        s -= float(np.clip(b * 0.10, -0.15, 0.15))
    stretch = None
    e200, atr = _last(c.ema200), _last(c.atr)
    if e200 and atr:
        stretch = (_last(c.close) - e200) / atr
        if stretch > 5:
            s -= 0.10
        elif stretch < -5:
            s += 0.10
    r.score = s
    r.state = int(np.sign(s)) if abs(s) >= 0.05 else 0
    r.meta.update({"z20": a, "z50": b, "stretch_atr": stretch})
    word = "stretched up" if a > 1.5 else "stretched down" if a < -1.5 else "near its mean"
    z50_txt = f", z50 {b:+.1f}" if b is not None else ""
    r.status = f"z20 {a:+.1f}{z50_txt} — {word}." + (
        f" {abs(stretch):.1f} ATR {'above' if stretch > 0 else 'below'} the 200-EMA." if stretch and abs(stretch) > 5 else "")
    return r


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------
def evaluate(
    df: pd.DataFrame,
    *,
    benchmark: pd.Series | None = None,
    benchmark_name: str | None = None,
    htf_rule: str | None = "W-FRI",
    htf_label: str = "Weekly",
) -> dict[str, RuleOutput]:
    """Run every rule on `df` (from build_frame). `benchmark` is a close series aligned to df's index."""
    c = _Calc(df)
    outs = [
        rule_trend_ema200(c), rule_rsi(c), rule_macd(c), rule_adx(c), rule_breakout(c), rule_obv(c),
        rule_unusual_volume(c), rule_support_resistance(c), rule_candles(c), rule_chart_patterns(c),
        rule_htf_trend(c, htf_rule, htf_label), rule_relative_strength(c, benchmark, benchmark_name),
        rule_bollinger(c), rule_zscore(c),
    ]
    return {o.id: o for o in outs}


def align_benchmark(df: pd.DataFrame, bench_bars: list[dict] | None, time_key: str = "date") -> pd.Series | None:
    """Benchmark closes aligned to df rows (last known benchmark close at or before each bar)."""
    if not bench_bars:
        return None
    b = build_frame(bench_bars, time_key)[["ts", "close"]].rename(columns={"close": "bench"})
    left = df[["ts"]].reset_index()
    if left["ts"].dt.tz is not None and b["ts"].dt.tz is None:
        b["ts"] = b["ts"].dt.tz_localize("UTC")
    elif left["ts"].dt.tz is None and b["ts"].dt.tz is not None:
        b["ts"] = b["ts"].dt.tz_localize(None)
    merged = pd.merge_asof(left.sort_values("ts"), b.sort_values("ts"), on="ts", direction="backward")
    return merged.set_index("index")["bench"].sort_index()


def aggregate_technical(outs: dict[str, RuleOutput]) -> dict[str, Any]:
    """Technical module score from its rules: sum → ADX amplifier → higher-TF conflict damping."""
    rules = [outs[k] for k in TECHNICAL_RULES if k in outs]
    s = sum(r.score for r in rules)
    notes = [r.status for r in rules if r.score and r.id not in ("htf_trend",)]
    amp = outs["adx"].meta.get("amplifier", 1.0) if "adx" in outs else 1.0
    s *= amp
    htf = outs.get("htf_trend")
    htf_state = htf.meta.get("htf_state", 0) if htf else 0
    conflict = bool(htf_state and s and np.sign(s) == -htf_state)
    if conflict:
        s *= 0.6
        notes.append(f"Signals fight the {htf.name.lower()} — damped ×0.6.")
    elif htf_state:
        notes.append(htf.status)
    return {"score": float(np.clip(s, -1, 1)), "amplifier": amp, "htf_state": htf_state,
            "htf_conflict": conflict, "notes": notes}


def aggregate_mean_reversion(outs: dict[str, RuleOutput]) -> dict[str, Any]:
    rules = [outs[k] for k in MEAN_REVERSION_RULES if k in outs]
    s = sum(r.score for r in rules)
    return {"score": float(np.clip(s, -1, 1)), "notes": [r.status for r in rules if r.score]}


FORWARD_BARS = (5, 20)


def _forward_returns(closes: np.ndarray, i: int) -> dict[str, float | None]:
    """Price change N bars after bar i — for judging past signals, never for generating them."""
    out = {}
    for n in FORWARD_BARS:
        out[f"ret_{n}"] = float(closes[i + n] / closes[i] - 1) if i + n < len(closes) and closes[i] else None
    return out


def _signal_stats(events: list[dict]) -> dict:
    """Track record of one rule's signals: count, how often they 'worked'
    (price up after a buy / down after a sell) and the average move."""
    stats = {}
    for side in ("buy", "sell"):
        evs = [e for e in events if e["side"] == side]
        s = {"n": len(evs)}
        for n in FORWARD_BARS:
            rets = [e[f"ret_{n}"] for e in evs if e.get(f"ret_{n}") is not None]
            s[f"n_eval_{n}"] = len(rets)
            if rets:
                worked = [r > 0 if side == "buy" else r < 0 for r in rets]
                s[f"win_{n}"] = sum(worked) / len(rets)
                s[f"avg_{n}"] = float(np.mean(rets))
        stats[side] = s
    return stats


def serialize(outs: dict[str, RuleOutput], times: list, start: int = 0, closes: np.ndarray | None = None) -> dict:
    """JSON for the chart: per-rule info, events and overlays with real bar times.

    Only bars from `start` on are emitted (indicators are still computed on
    the full history, so values are warmed up). With `closes`, each event
    also carries the price at the signal and the move 5 / 20 bars later,
    and each rule gets its signal track record."""
    def series(values: pd.Series, colors: list | None = None):
        out = []
        arr = values.to_numpy(dtype=float, na_value=np.nan)
        for i in range(start, len(arr)):
            v = arr[i]
            if np.isfinite(v):
                pt = {"time": times[i], "value": float(v)}
                if colors is not None:
                    pt["color"] = colors[i]
                out.append(pt)
        return out

    rules, events, overlays = [], [], {}
    for o in outs.values():
        evs = []
        for e in o.events:
            if e["i"] < start:
                continue
            ev = {"time": times[e["i"]], "rule": o.id, "side": e["side"], "label": e["label"]}
            if closes is not None:
                ev["price"] = float(closes[e["i"]])
                ev.update(_forward_returns(closes, e["i"]))
            evs.append(ev)
        events += evs
        rules.append({
            "id": o.id, "name": o.name, "category": o.category, "module": o.module,
            "description": o.description, "score": round(o.score, 4), "state": o.state,
            "status": o.status, "available": o.available,
            "meta": {k: v for k, v in o.meta.items() if k in ("support", "resistance", "adx", "amplifier", "htf_state")},
            "stats": _signal_stats(evs) if closes is not None else None,
        })
        ser = []
        for ov in o.overlays:
            t = ov["type"]
            if t in ("line", "histogram"):
                ser.append({k: v for k, v in ov.items() if k not in ("values", "colors")}
                           | {"data": series(ov["values"], ov.get("colors"))})
            elif t == "background":
                ser.append({"type": "background", "data": series(ov["values"].astype(float))})
            elif t == "levels":
                ser.append(ov)
            elif t == "segments":
                segs = []
                for sgm in ov["segments"]:
                    pts = [{"time": times[i], "value": float(p)} for i, p in sgm["points"] if i >= start]
                    if len(pts) >= 2:
                        segs.append({"points": pts, "color": sgm["color"], "dashed": sgm.get("dashed", False),
                                     "label": sgm.get("label")})
                ser.append({"type": "segments", "segments": segs})
        overlays[o.id] = ser
    events.sort(key=lambda e: (str(e["time"]) if isinstance(e["time"], str) else e["time"]))
    out = {"rules": rules, "events": events, "overlays": overlays}
    if closes is not None:
        # base rate: how often ANY bar was followed by a rise — a rule is only useful if it beats this
        base = {}
        for n in FORWARD_BARS:
            fwd = closes[start + n:] / closes[start:len(closes) - n] - 1 if len(closes) - n > start else np.array([])
            if len(fwd):
                base[f"up_{n}"] = float((fwd > 0).mean())
                base[f"avg_{n}"] = float(fwd.mean())
        out["base_rate"] = base
    return out
