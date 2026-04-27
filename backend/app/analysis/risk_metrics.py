"""Risk metrics module — beta, vol, max drawdown, Sharpe.

These are properties of the ticker, not directional signals — so this
module reports `score` near 0 by default and high `confidence`. Synthesis
uses these as RISK FILTERS (e.g. Conservative profile excludes beta > 1.5)
rather than as buy/sell drivers.

Lookback: 3 years (or whatever's available).
"""

from __future__ import annotations

import pandas as pd

from app.analysis.base import (
    AnalysisContext,
    BaseAnalysisModule,
    ModuleResult,
    clamp,
    no_data,
)


class RiskMetricsModule(BaseAnalysisModule):
    name = "risk_metrics"
    description = "Beta, vol, max drawdown, Sharpe — used as risk filters in synthesis."

    HORIZON_WEIGHTS = {
        "1w": 0.4, "2w": 0.4, "1m": 0.5, "3m": 0.6,
        "6m": 0.7, "1y": 0.8, "3y": 0.9,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        bars = (ctx.ohlcv or {}).get("bars") if ctx.ohlcv else None
        if not bars or len(bars) < 252:
            r = no_data(self.name, "need >= 1y of bars for risk metrics")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        closes = pd.Series(
            [b.get("adj_close") or b.get("close") for b in bars],
            index=pd.to_datetime([b["date"] for b in bars]),
        ).sort_index()
        rets = closes.pct_change().dropna()

        # 3y window or all available
        rets_3y = rets.tail(252 * 3)

        vol_annualized = float(rets_3y.std() * (252 ** 0.5))
        max_dd = _max_drawdown(closes.tail(252 * 3))
        sharpe_3y = float(rets_3y.mean() / rets_3y.std() * (252 ** 0.5)) if rets_3y.std() else 0.0

        beta = None
        bench_bars = (ctx.benchmark_ohlcv or {}).get("bars") if ctx.benchmark_ohlcv else None
        if bench_bars:
            bench_closes = pd.Series(
                [b.get("adj_close") or b.get("close") for b in bench_bars],
                index=pd.to_datetime([b["date"] for b in bench_bars]),
            ).sort_index()
            bench_rets = bench_closes.pct_change().dropna()
            joined = pd.concat([rets_3y, bench_rets], axis=1, join="inner").dropna()
            joined.columns = ["t", "b"]
            if len(joined) >= 60 and joined["b"].var() > 0:
                beta = float(joined["t"].cov(joined["b"]) / joined["b"].var())

        # Score is intentionally near zero — this module is a filter, not a driver.
        # We do however give a tiny positive bias to high-Sharpe names and a
        # tiny negative to deep-drawdown names.
        s = 0.0
        if sharpe_3y > 1.0:
            s += 0.05
        elif sharpe_3y < 0:
            s -= 0.05
        if max_dd is not None and max_dd < -0.50:
            s -= 0.05  # severe historical drawdown

        return ModuleResult(
            module=self.name,
            score=clamp(s),
            direction="neutral",
            confidence=0.85,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "beta_3y": beta,
                "vol_3y_annualized_pct": round(vol_annualized * 100, 2),
                "max_drawdown_3y_pct": round(max_dd * 100, 2) if max_dd is not None else None,
                "sharpe_3y": round(sharpe_3y, 3),
            },
            notes=_notes(beta, vol_annualized, max_dd, sharpe_3y),
            data_quality="full" if beta is not None else "partial",
        )


def _max_drawdown(closes: pd.Series) -> float | None:
    if len(closes) < 30:
        return None
    cum_max = closes.cummax()
    dd = (closes / cum_max - 1).min()
    return float(dd) if not pd.isna(dd) else None


def _notes(beta, vol, dd, sharpe) -> list[str]:
    out = []
    if beta is not None:
        out.append(f"Beta vs benchmark: {beta:.2f}.")
    if vol is not None:
        out.append(f"3-year annualized volatility: {vol * 100:.1f}%.")
    if dd is not None:
        out.append(f"3-year max drawdown: {dd * 100:.1f}%.")
    if sharpe:
        out.append(f"3-year Sharpe: {sharpe:.2f}.")
    return out
