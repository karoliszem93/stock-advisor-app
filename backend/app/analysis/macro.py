"""Macro context module.

Reads ctx.macro: the FRED bundle (VIX, 10Y, 2Y, T10Y2Y spread, unemployment,
USD/EUR, USD/GBP) and the euro-area bundle (VSTOXX, ECB deposit rate, euro
10Y yield, HICP inflation, EU economic sentiment). A US and a euro-area score
are computed separately and blended by the asset's European exposure (e.g. a
European-equity ETF is mostly euro-driven, an S&P 500 ETF not at all).

It modulates the suggestion in different directions depending on asset class:

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
    description = "US (VIX, curve, rates) + euro area (VSTOXX, ECB, HICP, sentiment) risk-on/off proxy."

    HORIZON_WEIGHTS = {
        "1w": 0.40, "2w": 0.50, "1m": 0.65,
        "3m": 0.80, "6m": 0.80, "1y": 0.65, "3y": 0.40,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        m = ctx.macro or {}
        us_s, us_notes, us_raw = _us_score(m)
        eu_s, eu_notes, eu_raw = _eu_score(m)
        if us_s is None and eu_s is None:
            r = no_data(self.name, "no macro data (FRED and ECB/Eurostat/STOXX all unavailable)")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        eu_w = _eu_exposure(ctx)
        if us_s is None:
            s, eu_w = eu_s, 1.0
        elif eu_s is None:
            s, eu_w = us_s, 0.0
        else:
            s = (1 - eu_w) * us_s + eu_w * eu_s
        notes = (us_notes if eu_w < 0.9 else []) + ([f"Euro area: {n}" for n in eu_notes] if eu_w > 0.1 else [])
        if 0.1 < eu_w < 0.9:
            notes.append(f"Macro blended {1 - eu_w:.0%} US / {eu_w:.0%} euro area by exposure.")

        score = clamp(s, -0.25, 0.25)
        confidence = 0.6
        if us_raw.get("vix") is not None and us_raw.get("us10y") is not None:
            confidence += 0.10
        if eu_s is not None and eu_w > 0.1:
            confidence += 0.10
        confidence = clamp(confidence, 0.0, 1.0)

        return ModuleResult(
            module=self.name,
            score=score,
            direction=direction_from_score(score, threshold=0.05),
            confidence=confidence,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={**us_raw, **eu_raw, "us_score": us_s, "eu_score": eu_s, "eu_exposure": eu_w},
            notes=notes,
            data_quality="full" if us_s is not None and (eu_s is not None or eu_w == 0) else "partial",
        )


def _val(m: dict, key: str, field: str = "value"):
    return (m.get(key) or {}).get(field)


def _us_score(m: dict) -> tuple[float | None, list[str], dict]:
    """US conditions from the FRED bundle; None when FRED data is absent."""
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

    raw = {
        "vix": vix,
        "us10y": us10y,
        "us10y_delta_7d": us10y_d,
        "yield_curve_2_10": spread,
        "unemployment_rate": unrate,
    }
    if vix is None and us10y is None and spread is None:
        return None, [], raw
    return clamp(s, -0.25, 0.25), notes, raw


def _eu_score(m: dict) -> tuple[float | None, list[str], dict]:
    """Euro-area conditions from the ECB / Eurostat / STOXX bundle."""
    vstoxx = _val(m, "VSTOXX")
    ea10y_d = _val(m, "EA_10Y", "delta_7d")
    dfr = _val(m, "ECB_DFR")
    dfr_d90 = _val(m, "ECB_DFR", "delta_90d")
    hicp = _val(m, "EA_HICP")
    esi = _val(m, "EU_ESI")
    esi_d90 = _val(m, "EU_ESI", "delta_90d")
    raw = {
        "vstoxx": vstoxx, "ea10y": _val(m, "EA_10Y"), "ea10y_delta_7d": ea10y_d,
        "ecb_deposit_rate": dfr, "ecb_rate_change_90d": dfr_d90,
        "ea_hicp": hicp, "eu_esi": esi, "eu_esi_change_3m": esi_d90, "eurusd": _val(m, "EURUSD"),
    }
    if all(v is None for v in (vstoxx, ea10y_d, dfr, hicp, esi)):
        return None, [], raw

    s = 0.0
    notes: list[str] = []
    if vstoxx is not None:
        if vstoxx < 16:
            s += 0.10
            notes.append(f"VSTOXX {vstoxx:.1f} — low fear.")
        elif vstoxx > 25:
            s -= 0.15
            notes.append(f"VSTOXX {vstoxx:.1f} — elevated fear.")
    if ea10y_d is not None:
        if ea10y_d <= -0.10:
            s += 0.05
            notes.append(f"Euro 10Y yield fell {ea10y_d * 100:+.0f}bp w/w.")
        elif ea10y_d >= 0.10:
            s -= 0.05
            notes.append(f"Euro 10Y yield rose {ea10y_d * 100:+.0f}bp w/w.")
    if dfr_d90 is not None and dfr is not None:
        if dfr_d90 < 0:
            s += 0.05
            notes.append(f"ECB cutting — deposit rate {dfr:.2f}% ({dfr_d90 * 100:+.0f}bp in 3m).")
        elif dfr_d90 > 0:
            s -= 0.05
            notes.append(f"ECB hiking — deposit rate {dfr:.2f}% ({dfr_d90 * 100:+.0f}bp in 3m).")
    if hicp is not None and hicp > 3.0:
        s -= 0.05
        notes.append(f"Inflation {hicp:.1f}% — well above the ECB's 2% target (hawkish risk).")
    if esi is not None:
        if esi > 100 and (esi_d90 or 0) >= 0:
            s += 0.05
            notes.append(f"Economic sentiment {esi:.1f} — above long-term average.")
        elif esi < 95 or (esi_d90 is not None and esi_d90 < -2):
            s -= 0.05
            notes.append(f"Economic sentiment {esi:.1f} — weak / deteriorating.")
    return clamp(s, -0.25, 0.25), notes, raw


_EU_COUNTRIES = {
    "France", "Germany", "Netherlands", "Italy", "Spain", "Belgium", "Ireland", "Austria",
    "Finland", "Portugal", "Greece", "Luxembourg", "Lithuania", "Latvia", "Estonia",
    "Slovakia", "Slovenia", "Croatia", "Cyprus", "Malta", "Bulgaria",
}
# Approximate share of euro-area exposure by curated ETF category
_CATEGORY_EU_WEIGHT = {
    "europe_developed": 0.85, "bonds_eu_govt": 0.9, "bonds_eu_corp": 0.85,
    "global_developed_em": 0.15, "global_developed": 0.2, "global_dividend": 0.25,
    "factor_quality": 0.2, "factor_value": 0.2, "factor_momentum": 0.2, "factor_low_vol": 0.2,
    "thematic_clean_energy": 0.25, "thematic_automation": 0.2, "thematic_ev": 0.2,
    "bonds_global": 0.25, "emerging_markets": 0.05, "japan": 0.05, "commodities_gold": 0.1,
}


def _eu_exposure(ctx: AnalysisContext) -> float:
    """0..1 share of the asset's drivers that are euro-area (0 = purely US)."""
    category = (ctx.metadata or {}).get("category")
    if category:
        return _CATEGORY_EU_WEIGHT.get(category, 0.0)  # us_* categories -> 0
    country = (ctx.info or {}).get("country")
    return 0.85 if country in _EU_COUNTRIES else 0.0
