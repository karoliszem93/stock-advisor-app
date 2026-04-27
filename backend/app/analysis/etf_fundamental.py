"""ETF-specific fundamentals module.

For ETFs, traditional P/E doesn't apply directly. What matters:
  - Expense ratio (low is better; >0.5% is a strike for passive ETFs)
  - AUM / liquidity (very small AUM = wider spreads, closure risk)
  - Domicile (Irish UCITS preferred for LT residents; US-domiciled ETFs
    have 30% dividend withholding without easy reclaim)
  - Distribution policy (accumulating defers LT capital-gains tax)
  - Tracking error (when comparing to a benchmark of the same index)

Score is small — ETF "buy/avoid" is mostly a momentum + macro decision,
not a fundamentals decision. This module mainly emits NOTES that the
LLM analyst weaves into the thesis (e.g. "Irish UCITS — favorable for
LT resident").
"""

from __future__ import annotations

from app.analysis.base import (
    AnalysisContext,
    BaseAnalysisModule,
    ModuleResult,
    clamp,
    direction_from_score,
)


class EtfFundamentalModule(BaseAnalysisModule):
    name = "etf_fundamental"
    description = "ETF expense / AUM / domicile / distribution; LT-tax annotations."
    applies_to = ("etf",)

    HORIZON_WEIGHTS = {
        "1w": 0.10, "2w": 0.10, "1m": 0.20,
        "3m": 0.40, "6m": 0.60, "1y": 0.80, "3y": 1.00,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        info = ctx.info or {}
        etf_info = ctx.etf_info or {}
        meta = ctx.metadata or {}

        # Combine sources, preferring curated metadata where present
        domicile = meta.get("domicile") or etf_info.get("domicile") or _infer_domicile(ctx.ticker)
        distribution = (meta.get("distribution") or etf_info.get("distribution")
                        or _infer_distribution(info))
        expense_ratio = (info.get("expense_ratio") or etf_info.get("expense_ratio")
                         or etf_info.get("expenseRatio"))
        aum = info.get("total_assets") or etf_info.get("aum") or etf_info.get("totalAssets")

        s = 0.0
        notes: list[str] = []

        # Domicile / tax treatment for LT resident
        if domicile == "IE":
            s += 0.05
            notes.append("Irish UCITS — favourable for an LT resident: 15% US dividend withholding via treaty.")
        elif domicile == "US":
            s -= 0.10
            notes.append("US-domiciled — 30% US dividend withholding without easy reclaim. Consider Irish UCITS equivalent.")
        elif domicile == "JE":
            notes.append("Jersey-domiciled (commodity ETC) — verify VAT/tax treatment for LT.")

        # Distribution policy
        if distribution == "accumulating":
            s += 0.03
            notes.append("Accumulating share class — defers LT capital-gains tax until sale.")
        elif distribution == "distributing":
            notes.append("Distributing — LT 15% dividend tax applies annually on payouts.")

        # Expense ratio
        if expense_ratio is not None:
            try:
                er = float(expense_ratio)
                if er < 0.0025:
                    s += 0.05
                    notes.append(f"Expense ratio {er * 100:.2f}% — very cheap.")
                elif er < 0.005:
                    s += 0.02
                elif er > 0.0075:
                    s -= 0.05
                    notes.append(f"Expense ratio {er * 100:.2f}% — above average for passive ETFs.")
            except (ValueError, TypeError):
                pass

        # AUM / liquidity
        if aum is not None:
            try:
                aum_num = float(aum)
                if aum_num < 50_000_000:  # < $50M
                    s -= 0.10
                    notes.append(f"AUM ~${aum_num / 1e6:.0f}M — small fund, watch spreads and closure risk.")
                elif aum_num > 1_000_000_000:
                    s += 0.02
            except (ValueError, TypeError):
                pass

        score = clamp(s)
        confidence = 0.6 if domicile else 0.4

        return ModuleResult(
            module=self.name,
            score=score,
            direction=direction_from_score(score, threshold=0.05),
            confidence=confidence,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "domicile": domicile,
                "distribution": distribution,
                "expense_ratio": expense_ratio,
                "aum": aum,
                "category": meta.get("category"),
            },
            notes=notes,
            data_quality="full" if domicile and distribution else "partial",
        )


def _infer_domicile(ticker: str) -> str | None:
    """Cheap inference from ticker suffix when no provider data is available."""
    upper = ticker.upper()
    if upper.endswith(".L"):  # London-listed; many UCITS list there
        return "IE"  # most likely; can be wrong but a sane default
    if upper.endswith(".DE") or upper.endswith(".AS"):
        return "IE"  # most German/Dutch-listed UCITS are Irish-domiciled
    if "." not in upper:
        return "US"
    return None


def _infer_distribution(info: dict) -> str | None:
    cat = (info.get("category") or "").lower()
    name = (info.get("long_name") or "").lower()
    text = f"{cat} {name}"
    if "(acc)" in text or "accumulating" in text or "acc " in text:
        return "accumulating"
    if "(dist)" in text or "distributing" in text or "dist " in text:
        return "distributing"
    return None
