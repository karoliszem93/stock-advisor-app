"""Insider transactions, short interest + institutional holdings.

Reads ctx.insider — combined view from EDGAR Form 4 summary + Finnhub
insider transactions endpoint (US only), plus ctx.insider["ownership"]:
FINRA short interest (US) and Yahoo short % of float / institutional
ownership (any listing).

Heavy or rising short interest is a bearish crowd signal (with squeeze risk
noted); falling short interest mildly positive.

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
    description = "Insider buying/selling (Form 4 + Finnhub) and short interest (FINRA + Yahoo)."
    applies_to = ("equity",)

    HORIZON_WEIGHTS = {
        "1w": 0.30, "2w": 0.40, "1m": 0.65,
        "3m": 0.85, "6m": 0.85, "1y": 0.65, "3y": 0.40,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        ins = ctx.insider or {}
        own = ins.get("ownership") or {}
        has_insider = any(k in ins for k in ("insider_buys_90d", "insider_sells_90d"))
        if not has_insider and not own:
            r = no_data(self.name, "no insider or ownership data available")
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

        # ---- Short interest ----
        short_pct = own.get("short_pct_float")
        dtc = own.get("days_to_cover") or own.get("short_ratio_days")
        short_chg = own.get("short_change_pct")
        if short_pct is not None and short_pct > 0.15:
            s -= 0.05
            notes.append(f"Short interest {short_pct * 100:.0f}% of float — heavily shorted (squeeze risk both ways).")
        elif dtc is not None and dtc > 7:
            s -= 0.03
            notes.append(f"{dtc:.1f} days to cover short positions — crowded short.")
        if short_chg is not None:
            if short_chg > 0.15:
                s -= 0.05
                notes.append(f"Short interest up {short_chg * 100:.0f}% since last FINRA report.")
            elif short_chg < -0.15:
                s += 0.03
                notes.append(f"Short interest down {-short_chg * 100:.0f}% since last FINRA report.")

        inst = own.get("held_pct_institutions")
        if inst is not None:
            notes.append(f"Institutions hold {min(inst, 1.0) * 100:.0f}% of shares.")

        score = clamp(s, -0.20, 0.20)
        confidence = clamp(0.5 + (0.1 if (buys + sells) >= 5 else 0), 0.0, 1.0)
        if not has_insider:
            confidence = 0.35  # short interest / ownership alone is a weaker signal

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
                "short_pct_float": short_pct,
                "days_to_cover": dtc,
                "short_change_pct": short_chg,
                "short_settlement_date": own.get("settlement_date"),
                "held_pct_institutions": inst,
            },
            notes=notes,
            data_quality="full" if (buys + sells) >= 5 else "partial",
        )
