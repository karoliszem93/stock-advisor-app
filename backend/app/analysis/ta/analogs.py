"""Similar-situation (analog) analysis — information only, NOT used in scoring.

Describes every past daily bar by a fingerprint of chart readings (trend,
momentum, stretch, volatility, position in range, weekly trend), finds the
past bars whose fingerprint is closest to today's, and reports what the
price did next (5 / 20 / 60 bars), compared with the base rate.

No look-ahead: every fingerprint value at bar i uses only data up to bar i
(the weekly trend uses completed weeks only). Outcomes are read after the
fact, for judging, never for building fingerprints. Feature scaling uses
the whole history's spread — that only sets units and leaks no outcomes.

Matches are taken greedily from the closest, at least MIN_GAP bars apart, so
each counts as a separate episode rather than ten days of the same move.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.analysis.ta import indicators as ind
from app.analysis.ta import rules as ta

HORIZONS = (5, 20, 60)
MIN_GAP = 15          # bars between selected episodes
EXCLUDE_RECENT = 20   # today's own move isn't a "past" situation
DEFAULT_K = 20


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    weight: float
    fmt: str  # "pct" | "num0" | "num1" | "num2" | "trend"


FEATURES = (
    Feature("dist200", "Distance from 200-EMA", 1.0, "pct"),
    Feature("ret63", "3-month return", 1.0, "pct"),
    Feature("ret21", "1-month return", 0.8, "pct"),
    Feature("rsi", "RSI (14)", 1.0, "num0"),
    Feature("adx", "ADX (14)", 0.7, "num0"),
    Feature("macd_n", "MACD histogram (in ATRs)", 0.7, "num2"),
    Feature("z20", "Z-score 20", 0.8, "num1"),
    Feature("z50", "Z-score 50", 0.8, "num1"),
    Feature("vol_pct", "Volatility percentile (2y)", 0.7, "pct0"),
    Feature("range_pos", "Position in 20-bar range", 0.7, "pct0"),
    Feature("weekly", "Weekly trend", 1.0, "trend"),
)


def fingerprints(df: pd.DataFrame) -> pd.DataFrame:
    """One row of features per bar (NaN until each indicator has warmed up)."""
    c = df["close"]
    atr = ind.atr(df, 14)
    rets = c.pct_change()
    vol30 = rets.rolling(30, min_periods=30).std()
    hh = df["high"].rolling(20, min_periods=20).max()
    ll = df["low"].rolling(20, min_periods=20).min()
    weekly = ta.rule_htf_trend(ta.Calc(df), "W-FRI", "Weekly")
    wk = next((o["values"] for o in weekly.overlays if o["type"] == "background"), None)
    return pd.DataFrame({
        "dist200": c / ind.ema(c, 200) - 1,
        "ret63": c / c.shift(63) - 1,
        "ret21": c / c.shift(21) - 1,
        "rsi": ind.rsi(c, 14),
        "adx": ind.adx(df, 14)["adx"],
        "macd_n": ind.macd(c)["hist"] / atr,
        "z20": ind.zscore(c, 20),
        "z50": ind.zscore(c, 50),
        "vol_pct": vol30.rolling(504, min_periods=252).rank(pct=True),
        "range_pos": (c - ll) / (hh - ll).replace(0, np.nan),
        "weekly": (wk if wk is not None else pd.Series(0, index=df.index)).astype(float).to_numpy(),
    }, index=df.index)


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    a = np.array(values)
    return {
        "n": len(a),
        "up": float((a > 0).mean()),
        "median": float(np.median(a)),
        "mean": float(a.mean()),
        "p10": float(np.percentile(a, 10)),
        "p90": float(np.percentile(a, 90)),
        "best": float(a.max()),
        "worst": float(a.min()),
    }


def today_fingerprint(df: pd.DataFrame) -> dict | None:
    """Fingerprint of the last bar, or None if history is too short to compute it."""
    row = fingerprints(df).iloc[-1]
    return None if row.isna().any() else {c: float(row[c]) for c in row.index}


def find_analogs(df: pd.DataFrame, k: int = DEFAULT_K, today: dict | None = None) -> dict:
    """Closest past situations in `df` and what followed.

    `today` is the situation to look for (default: the last bar of `df`).
    Passing the ticker's own fingerprint while `df` is a long-history proxy
    asks "when did the proxy look the way this ticker looks now?" — the
    features are ratios / oscillators, so they compare across instruments.
    """
    n = len(df)
    feats = fingerprints(df)
    valid = feats.notna().all(axis=1).to_numpy()
    cols = [f.key for f in FEATURES]
    if today is None:
        if not valid[-1]:
            return {"available": False, "reason": "Not enough history to describe today's situation (needs ~2 years)."}
        today = {c: float(feats.iloc[-1][c]) for c in cols}
    if valid.sum() < 500:
        return {"available": False, "reason": "Not enough history to search (needs ~3 years)."}
    hist = feats[valid]
    med = hist.median()
    spread = ((hist.quantile(0.75) - hist.quantile(0.25)) / 1.349).replace(0, np.nan)
    spread["weekly"] = 1.0  # categorical -1/0/+1 keeps its own scale
    med["weekly"] = 0.0
    X = ((hist[cols] - med[cols]) / spread[cols]).to_numpy()
    tvec = ((pd.Series(today)[cols] - med[cols]) / spread[cols]).to_numpy(float)
    w = np.array([f.weight for f in FEATURES])
    idx = np.flatnonzero(valid)
    dist = np.sqrt((((X - tvec) ** 2) * w).sum(axis=1) / w.sum())

    close = df["close"].to_numpy(float)
    low = df["low"].to_numpy(float)
    high = df["high"].to_numpy(float)
    cand = [(d, i) for d, i in zip(dist, idx, strict=True) if i < n - 1 - EXCLUDE_RECENT and i + 5 < n]
    cand.sort()
    picked: list[int] = []
    for _, i in cand:
        if all(abs(i - j) >= MIN_GAP for j in picked):
            picked.append(i)
            if len(picked) >= k:
                break

    rank_of = {i: r for r, (_, i) in enumerate(cand)}
    dist_of = dict(zip(idx.tolist(), dist.tolist(), strict=True))
    times = list(df["time"])
    matches, paths = [], []
    for i in picked:
        m = {
            "time": times[i],
            "close": float(close[i]),
            # how close it is: share of all past days that were further away
            "similarity": 1 - rank_of[i] / max(len(cand), 1),
            "distance": float(dist_of[i]),
        }
        for h in HORIZONS:
            m[f"ret_{h}"] = float(close[i + h] / close[i] - 1) if i + h < n else None
        end = min(i + 20, n - 1)
        if end > i:
            m["dip_20"] = float(low[i + 1:end + 1].min() / close[i] - 1)
            m["peak_20"] = float(high[i + 1:end + 1].max() / close[i] - 1)
        m["features"] = {c: _num(feats.iloc[i][c]) for c in cols}
        matches.append(m)
        last = min(i + 60, n - 1)
        paths.append({"time": times[i], "values": [float(close[j] / close[i]) for j in range(i, last + 1)]})

    summary = {}
    for h in HORIZONS:
        vals = [m[f"ret_{h}"] for m in matches if m[f"ret_{h}"] is not None]
        # base rate: every described day with h bars of future, regardless of situation
        base_idx = idx[idx + h < n]
        fwd = close[base_idx + h] / close[base_idx] - 1
        summary[str(h)] = {"analogs": _stats(vals), "base": _stats(list(fwd))}
    dips = [m["dip_20"] for m in matches if m.get("dip_20") is not None and m["ret_20"] is not None]
    summary["dip_20"] = _stats(dips)

    return {
        "available": True,
        "today": {c: _num(today[c]) for c in cols},
        "features": [{"key": f.key, "label": f.label, "weight": f.weight, "fmt": f.fmt} for f in FEATURES],
        "matches": sorted(matches, key=lambda m: -m["similarity"]),
        "paths": paths,
        "summary": summary,
        "verdict": _verdict(summary),
        "history_bars": int(valid.sum()),
        "history_from": times[int(idx[0])],
        "params": {"k": k, "min_gap": MIN_GAP, "horizons": list(HORIZONS)},
    }


def _verdict(summary: dict) -> dict:
    """Plain-language reading of the 20-bar outcome vs the base rate."""
    a, b = summary["20"]["analogs"], summary["20"]["base"]
    if a.get("n", 0) < 8 or not b.get("n"):
        return {"tone": "inconclusive", "text": "Too few comparable situations to draw a conclusion."}
    diff = a["up"] - b["up"]
    med_diff = a["median"] - b["median"]
    small = a["n"] < 12
    if diff >= 0.10 and med_diff > 0:
        tone, word = "better", "more often than usual"
    elif diff <= -0.10 and med_diff < 0:
        tone, word = "worse", "less often than usual"
    else:
        tone, word = "similar", "about as often as usual"
    text = (f"After the {a['n']} most similar past situations, price was higher 20 bars later "
            f"{a['up'] * 100:.0f}% of the time ({word}: {b['up'] * 100:.0f}% for any day), "
            f"median move {a['median'] * 100:+.1f}% vs {b['median'] * 100:+.1f}%.")
    if small:
        text += " Small sample — treat as a weak hint."
    return {"tone": tone, "text": text}


def _num(v) -> float | None:
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v) else float(v)
