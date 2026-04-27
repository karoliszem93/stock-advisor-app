"""Insider transactions + institutional holdings.

Reads ctx.insider — combined view from EDGAR Form 4 summary + Finnhub
insider transactions endpoint (the data-snapshot stage merges them).

Insider buying is a classic positive signal (insiders typically only buy
when they believe shares are undervalued). Insider selling is noisier
(can be tax/diversification), so we weight buys more than sells.
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


class InsiderInstitutionalModule(BaseAnalysisModule):
    name = "insider_institutional"
    description = "Insider buying/selling activity from Form 4 + Finnhub."
    applies_to = ("equity",)

    HORIZON_WEIGHTS = {
        "1w": 0.30, "2w": 0.40, "1m": 0.65,
        "3m": 0.85, "6m": 0.85, "1y": 0.65, "3y": 0.40,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        ins = ctx.insider or {}
        if not ins:
            r = no_data(self.name, "no insider data available")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        # Expected fields (set by the snapshot stage):
        #   insider_buys_90d      (count)
        #   insider_sells_90d     (count)
        #   net_share_change_pct  (sign matters; small magnitude)
        #   net_value_usd_90d     (positive = net buys, negative = net sells)
        buys = ins.get("insider_buys_90d") or 0
        sells = ins.get("insider_sells_90d") or 0
        net_value = ins.get("net_value_usd_90d") or 0
        net_pct = ins.get("net_share_change_pct") or 0

        s = 0.0
        notes: list[str] = []

        if buys > sells * 1.5 and buys >= 2:
            s += 0.15
            notes.append(f"Insiders bought ({buys}) more than sold ({sells}) over 90 days.")
        elif sells > buys * 2 and sells >= 3:
            s -= 0.10
            notes.append(f"Insiders sold ({sells}) more than bought ({buys}) over 90 days.")

        if net_value > 1_000_000:
            s += 0.05
            notes.append(f"Net insider buys ~${net_value / 1e6:.1f}M (90d).")
        elif net_value < -5_000_000:
            s -= 0.05
            notes.append(f"Net insider sells ~${-net_value / 1e6:.1f}M (90d).")

        if net_pct > 0.005:
            s += 0.05
        elif net_pct < -0.01:
            s -= 0.05

        score = clamp(s, -0.20, 0.20)
        confidence = clamp(0.5 + (0.1 if (buys + sells) >= 5 else 0), 0.0, 1.0)

        return ModuleResult(
            module=self.name,
            score=score,
            direction=direction_from_score(score, threshold=0.05),
            confidence=confidence,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "insider_buys_90d": buys,
                "insider_sells_90d": sells,
                "net_value_usd_90d": net_value,
                "net_share_change_pct": net_pct,
            },
            notes=notes,
            data_quality="full" if (buys + sells) >= 5 else "partial",
        )
