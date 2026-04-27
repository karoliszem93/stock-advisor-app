"""Macro context module.

Reads ctx.macro (FRED bundle: VIX, 10Y, 2Y, T10Y2Y spread, unemployment,
USD/EUR, USD/GBP). The macro signal is global — same value for every
ticker on a given run — but it modulates the suggestion in different
directions depending on asset class:

  - Risk-on assets (high-beta tech, growth equities, cyclical sectors)
    benefit from low VIX + falling rates + steepening curve.
  - Risk-off assets (defensives, dividend stocks, bonds, gold) benefit
    when those signals invert.

We emit a *positive-leaning* score for risk-on environments and rely on
synthesis to flip the sign for defensive assets.
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


class MacroModule(BaseAnalysisModule):
    name = "macro"
    description = "VIX / yield curve / rates / FX — global risk-on/off proxy."

    HORIZON_WEIGHTS = {
        "1w": 0.40, "2w": 0.50, "1m": 0.65,
        "3m": 0.80, "6m": 0.80, "1y": 0.65, "3y": 0.40,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        m = ctx.macro or {}
        if not m:
            r = no_data(self.name, "no macro bundle (FRED key missing or call failed)")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        vix = (m.get("VIXCLS") or {}).get("value")
        us10y = (m.get("DGS10") or {}).get("value")
        us10y_d = (m.get("DGS10") or {}).get("delta_7d")
        spread = (m.get("T10Y2Y") or {}).get("value")
        unrate = (m.get("UNRATE") or {}).get("value")

        s = 0.0
        notes: list[str] = []

        # VIX
        if vix is not None:
            if vix < 15:
                s += 0.10
                notes.append(f"VIX {vix:.1f} — low fear (risk-on environment).")
            elif vix > 25:
                s -= 0.15
                notes.append(f"VIX {vix:.1f} — elevated fear (risk-off environment).")

        # Rate trend (falling rates support multiples)
        if us10y_d is not None:
            if us10y_d <= -0.10:
                s += 0.08
                notes.append(f"10Y rate fell {us10y_d * 100:+.0f}bp w/w — multiple-expansion tailwind.")
            elif us10y_d >= 0.10:
                s -= 0.08
                notes.append(f"10Y rate rose {us10y_d * 100:+.0f}bp w/w — multiple-compression headwind.")

        # Yield curve (negative = recession concern)
        if spread is not None:
            if spread < 0:
                s -= 0.10
                notes.append(f"Yield curve inverted (10Y-2Y = {spread:+.2f}) — recession signal.")
            elif spread > 1.0:
                s += 0.05

        # Unemployment trend would be ideal — current level alone is weak signal
        # Skipping detailed unemployment scoring for v1.

        score = clamp(s, -0.25, 0.25)
        confidence = 0.6
        if vix is not None and us10y is not None:
            confidence += 0.15
        confidence = clamp(confidence, 0.0, 1.0)

        return ModuleResult(
            module=self.name,
            score=score,
            direction=direction_from_score(score, threshold=0.05),
            confidence=confidence,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "vix": vix,
                "us10y": us10y,
                "us10y_delta_7d": us10y_d,
                "yield_curve_2_10": spread,
                "unemployment_rate": unrate,
            },
            notes=notes,
            data_quality="full" if vix is not None and us10y is not None else "partial",
        )
