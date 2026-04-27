"""Equity fundamentals module.

Reads ctx.fundamentals (combined view from FMP / Alpha Vantage / EDGAR /
SimFin — assembled by the data-snapshot stage in the daily pipeline).

Score is built from valuation + profitability + growth + balance-sheet
strength. Each component is normalized via crude min/max bands chosen
from typical large-cap ranges; the synthesis layer can recalibrate these
thresholds from validation history once enough data exists.
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


class FundamentalEquityModule(BaseAnalysisModule):
    name = "fundamental_equity"
    description = "Valuation, profitability, growth, balance-sheet strength."
    applies_to = ("equity",)

    HORIZON_WEIGHTS = {
        "1w": 0.20, "2w": 0.30, "1m": 0.55,
        "3m": 0.85, "6m": 1.00, "1y": 1.00, "3y": 1.00,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        f = ctx.fundamentals or {}
        ttm = (f.get("ttm") or {})
        growth = (f.get("growth") or {})
        if not ttm and not growth:
            r = no_data(self.name, "no fundamentals available from any source")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        s = 0.0
        notes: list[str] = []

        # ---- Valuation ----
        pe = ttm.get("pe")
        pb = ttm.get("pb")
        ps = ttm.get("ps")
        peg = ttm.get("peg")
        ev_ebitda = ttm.get("ev_ebitda")
        fcf_yield = ttm.get("fcf_yield")

        if pe is not None and pe > 0:
            # P/E sweet spot ~10–25; very high P/E penalized
            if pe < 12:
                s += 0.15
                notes.append(f"P/E {pe:.1f} — undervalued vs market.")
            elif pe < 25:
                s += 0.05
            elif pe > 40:
                s -= 0.15
                notes.append(f"P/E {pe:.1f} — rich valuation.")

        if peg is not None and peg > 0:
            if peg < 1.0:
                s += 0.10
                notes.append(f"PEG {peg:.2f} — growth at reasonable price.")
            elif peg > 2.5:
                s -= 0.10
                notes.append(f"PEG {peg:.2f} — paying steep premium for growth.")

        if fcf_yield is not None:
            if fcf_yield > 0.06:
                s += 0.10
                notes.append(f"FCF yield {fcf_yield * 100:.1f}% — strong cash generation.")
            elif fcf_yield < 0.01:
                s -= 0.05

        if ps is not None and ps > 15:
            s -= 0.05  # P/S > 15 typically expensive software/biotech

        # ---- Profitability ----
        roe = ttm.get("roe")
        roic = ttm.get("roic")
        op_margin = ttm.get("op_margin")
        net_margin = ttm.get("net_margin")

        if roe is not None:
            if roe > 0.20:
                s += 0.15
                notes.append(f"ROE {roe * 100:.1f}% — strong returns on equity.")
            elif roe > 0.10:
                s += 0.05
            elif roe < 0:
                s -= 0.15
                notes.append(f"ROE {roe * 100:.1f}% — negative returns.")

        if roic is not None and roic > 0.15:
            s += 0.10
        if op_margin is not None and op_margin < 0:
            s -= 0.10

        # ---- Growth ----
        rev_3y = growth.get("rev_3y")
        eps_3y = growth.get("eps_3y")

        if rev_3y is not None:
            if rev_3y > 0.15:
                s += 0.15
                notes.append(f"Revenue growth (3y CAGR) {rev_3y * 100:.1f}%.")
            elif rev_3y < 0:
                s -= 0.10

        if eps_3y is not None:
            if eps_3y > 0.15:
                s += 0.10
            elif eps_3y < -0.10:
                s -= 0.15
                notes.append(f"EPS shrinking (3y) at {eps_3y * 100:.1f}%.")

        # ---- Balance sheet ----
        debt_to_equity = ttm.get("debt_to_equity")
        if debt_to_equity is not None:
            if debt_to_equity > 2.5:
                s -= 0.10
                notes.append(f"Debt/Equity {debt_to_equity:.1f} — leveraged.")
            elif debt_to_equity < 0.5:
                s += 0.05

        # ---- Earnings surprises (last 4 prints) ----
        history = f.get("earnings_history") or []
        recent = history[:4]
        beats = sum(1 for h in recent if (h.get("surprise_pct") or 0) > 0)
        if recent:
            if beats >= 3:
                s += 0.10
                notes.append(f"{beats}/4 recent earnings beats.")
            elif beats <= 1:
                s -= 0.05

        score = clamp(s)
        # Confidence scales with data coverage
        coverage_score = sum(1 for v in (pe, roe, rev_3y, debt_to_equity) if v is not None)
        confidence = clamp(0.4 + 0.15 * coverage_score, 0.0, 1.0)

        return ModuleResult(
            module=self.name,
            score=score,
            direction=direction_from_score(score),
            confidence=confidence,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "ttm": ttm,
                "growth": growth,
                "earnings_beats_last_4": beats,
                "source": f.get("source"),
            },
            notes=notes,
            data_quality="full" if coverage_score >= 4 else ("partial" if coverage_score else "missing"),
        )
