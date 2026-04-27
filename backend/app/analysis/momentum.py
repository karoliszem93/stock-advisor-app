"""Momentum module — multi-period returns + relative strength vs benchmark.

Looks at how the ticker has performed over rolling lookbacks and compares
against the broad-market benchmark (SPY for US, VWRL for global) and
sector ETF (when ctx.sector_ohlcv is supplied).

Score components:
  + 1m return (ranked vs benchmark)        ±0.20
  + 3m return (ranked vs benchmark)        ±0.25
  + 6m return (ranked vs benchmark)        ±0.20
  + 12m return                              ±0.15
  + Acceleration (3m better than 6m, etc.) ±0.10

Momentum is most informative on 1m–6m horizons; less so for very short
(noisy) and very long (mean-reverts) timeframes.
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


class MomentumModule(BaseAnalysisModule):
    name = "momentum"
    description = "Multi-period returns + relative strength vs benchmark/sector."

    HORIZON_WEIGHTS = {
        "1w": 0.40, "2w": 0.55, "1m": 0.85, "3m": 1.0,
        "6m": 0.85, "1y": 0.50, "3y": 0.20,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        bars = (ctx.ohlcv or {}).get("bars") if ctx.ohlcv else None
        if not bars or len(bars) < 60:
            r = no_data(self.name, "fewer than 60 daily bars")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        closes = _closes(bars)
        bench_closes = _closes((ctx.benchmark_ohlcv or {}).get("bars") or []) if ctx.benchmark_ohlcv else None
        sector_closes = _closes((ctx.sector_ohlcv or {}).get("bars") or []) if ctx.sector_ohlcv else None

        ret_1m = _return_pct(closes, 21)
        ret_3m = _return_pct(closes, 63)
        ret_6m = _return_pct(closes, 126)
        ret_12m = _return_pct(closes, 252)

        rs_3m_bench = _relative_strength(closes, bench_closes, 63) if bench_closes is not None else None
        rs_6m_bench = _relative_strength(closes, bench_closes, 126) if bench_closes is not None else None
        rs_3m_sector = _relative_strength(closes, sector_closes, 63) if sector_closes is not None else None

        acceleration = _acceleration(ret_1m, ret_3m, ret_6m)

        s = 0.0
        notes: list[str] = []

        # Direct returns (anchored to benchmark when present)
        if ret_3m is not None:
            s += clamp(ret_3m * 1.5, -0.25, 0.25)
            if abs(ret_3m) >= 0.05:
                notes.append(f"3-month return {ret_3m * 100:+.1f}%.")

        if ret_6m is not None:
            s += clamp(ret_6m * 0.8, -0.20, 0.20)

        if ret_12m is not None:
            s += clamp(ret_12m * 0.4, -0.15, 0.15)

        # Relative strength
        if rs_3m_bench is not None:
            s += clamp((rs_3m_bench - 1.0) * 1.5, -0.20, 0.20)
            if rs_3m_bench > 1.05:
                notes.append(f"Outperformed benchmark by {(rs_3m_bench - 1) * 100:.1f}% over 3m.")
            elif rs_3m_bench < 0.95:
                notes.append(f"Underperformed benchmark by {(1 - rs_3m_bench) * 100:.1f}% over 3m.")

        if rs_3m_sector is not None:
            s += clamp((rs_3m_sector - 1.0) * 1.0, -0.10, 0.10)

        if acceleration is not None:
            s += clamp(acceleration * 2, -0.10, 0.10)
            if acceleration > 0.03:
                notes.append("Momentum accelerating (recent returns outpacing trailing).")
            elif acceleration < -0.03:
                notes.append("Momentum decelerating.")

        score = clamp(s)

        confidence = 0.55
        if rs_3m_bench is not None:
            confidence += 0.15
        if len(closes) < 252:
            confidence -= 0.10
        confidence = clamp(confidence, 0.0, 1.0)

        return ModuleResult(
            module=self.name,
            score=score,
            direction=direction_from_score(score),
            confidence=confidence,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "ret_1m_pct": _pct(ret_1m),
                "ret_3m_pct": _pct(ret_3m),
                "ret_6m_pct": _pct(ret_6m),
                "ret_12m_pct": _pct(ret_12m),
                "rs_vs_benchmark_3m": rs_3m_bench,
                "rs_vs_benchmark_6m": rs_6m_bench,
                "rs_vs_sector_3m": rs_3m_sector,
                "acceleration": acceleration,
            },
            notes=notes,
            data_quality="full" if len(closes) >= 252 else "partial",
        )


def _closes(bars: list[dict] | None) -> pd.Series | None:
    if not bars:
        return None
    df = pd.DataFrame(bars)
    if "adj_close" in df:
        s = df["adj_close"].fillna(df.get("close"))
    else:
        s = df["close"]
    s.index = pd.to_datetime(df["date"])
    return s.sort_index()


def _return_pct(s: pd.Series, lookback_days: int) -> float | None:
    if s is None or len(s) <= lookback_days:
        return None
    end = s.iloc[-1]
    start = s.iloc[-lookback_days - 1]
    if start == 0 or pd.isna(start) or pd.isna(end):
        return None
    return float(end / start - 1)


def _relative_strength(s: pd.Series, bench: pd.Series, lookback_days: int) -> float | None:
    """Ratio of (1 + ticker_return) / (1 + benchmark_return) over the period."""
    r_ticker = _return_pct(s, lookback_days)
    r_bench = _return_pct(bench, lookback_days)
    if r_ticker is None or r_bench is None:
        return None
    return float((1 + r_ticker) / (1 + r_bench))


def _acceleration(r_1m: float | None, r_3m: float | None, r_6m: float | None) -> float | None:
    if r_1m is None or r_3m is None or r_6m is None:
        return None
    # annualize roughly: 1m * 12, 3m * 4, 6m * 2 → expect each annualized leg
    return float((r_1m * 12) - (r_3m * 4))


def _pct(x: float | None) -> float | None:
    return None if x is None else round(x * 100, 2)
