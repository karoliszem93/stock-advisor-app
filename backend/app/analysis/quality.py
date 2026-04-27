"""Quality scores — Piotroski F-Score, Altman Z-Score, Beneish M-Score.

These are well-known synthetic scores combining multiple fundamental
ratios into a single quality / fraud / bankruptcy proxy. We compute them
when the underlying ctx.fundamentals data is available; if any input is
missing, we report `partial` and skip that score.

Piotroski F-Score (0–9)  — higher = better
  Profitability (4):
    1. ROA > 0
    2. CFO > 0
    3. ΔROA > 0 (vs prior year)
    4. CFO > Net Income (quality of earnings)
  Leverage / Liquidity (3):
    5. ΔLong-term Debt < 0 (debt reduction)
    6. ΔCurrent Ratio > 0
    7. No new shares issued
  Operating efficiency (2):
    8. ΔGross Margin > 0
    9. ΔAsset Turnover > 0

Altman Z-Score (>2.99 safe; 1.81–2.99 grey; <1.81 distress)
  Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5

Beneish M-Score (< -2.22 = unlikely to manipulate; > -2.22 = flag)

When the data quality is too thin to compute robustly, we return what we
can with `data_quality=partial` and let synthesis weight the signal down.
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


class QualityModule(BaseAnalysisModule):
    name = "quality"
    description = "Piotroski F-Score, Altman Z, Beneish M (where data permits)."
    applies_to = ("equity",)

    HORIZON_WEIGHTS = {
        "1w": 0.20, "2w": 0.30, "1m": 0.50,
        "3m": 0.80, "6m": 1.00, "1y": 1.00, "3y": 1.00,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        f = ctx.fundamentals or {}
        income = f.get("income_periods") or []
        balance = f.get("balance_sheet_periods") or []
        cashflow = f.get("cash_flow_periods") or []

        if not income or not balance:
            r = no_data(self.name, "missing income/balance sheet periods")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        piotroski = _piotroski(income, balance, cashflow)
        altman_z = _altman_z(income[0] if income else {}, balance[0] if balance else {})
        beneish_m = _beneish_m(income, balance) if len(income) >= 2 and len(balance) >= 2 else None

        s = 0.0
        notes: list[str] = []

        if piotroski is not None:
            if piotroski >= 7:
                s += 0.20
                notes.append(f"Piotroski F-Score {piotroski}/9 — strong fundamental quality.")
            elif piotroski <= 3:
                s -= 0.15
                notes.append(f"Piotroski F-Score {piotroski}/9 — weak quality.")

        if altman_z is not None:
            if altman_z >= 3:
                s += 0.10
                notes.append(f"Altman Z {altman_z:.1f} — bankruptcy-safe zone.")
            elif altman_z < 1.81:
                s -= 0.20
                notes.append(f"Altman Z {altman_z:.1f} — distress zone.")

        if beneish_m is not None and beneish_m > -2.22:
            s -= 0.10
            notes.append(f"Beneish M {beneish_m:.2f} — possible earnings-manipulation flag.")

        score = clamp(s)
        confidence = 0.5
        if piotroski is not None:
            confidence += 0.2
        if altman_z is not None:
            confidence += 0.1
        confidence = clamp(confidence, 0.0, 1.0)

        return ModuleResult(
            module=self.name,
            score=score,
            direction=direction_from_score(score),
            confidence=confidence,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "piotroski_f": piotroski,
                "altman_z": altman_z,
                "beneish_m": beneish_m,
            },
            notes=notes,
            data_quality="full" if piotroski is not None and altman_z is not None else "partial",
        )


# ---------------------------------------------------------------------------
# Piotroski
# ---------------------------------------------------------------------------
def _piotroski(income: list[dict], balance: list[dict], cashflow: list[dict]) -> int | None:
    """Best-effort Piotroski F-Score. Returns None if essential rows missing."""
    if len(income) < 2 or len(balance) < 2 or not cashflow:
        return None

    cur_inc = income[0]
    prev_inc = income[1]
    cur_bal = balance[0]
    prev_bal = balance[1]
    cur_cf = cashflow[0] if cashflow else {}

    score = 0
    try:
        net_income = _g(cur_inc, "netIncome", "net_income")
        total_assets = _g(cur_bal, "totalAssets", "total_assets")
        roa = (net_income / total_assets) if (net_income is not None and total_assets) else None
        if roa is not None and roa > 0:
            score += 1

        cfo = _g(cur_cf, "operatingCashFlow", "cashFromOperations", "operating_cash_flow")
        if cfo is not None and cfo > 0:
            score += 1

        prev_ni = _g(prev_inc, "netIncome", "net_income")
        prev_ta = _g(prev_bal, "totalAssets", "total_assets")
        prev_roa = (prev_ni / prev_ta) if (prev_ni is not None and prev_ta) else None
        if roa is not None and prev_roa is not None and roa > prev_roa:
            score += 1

        if cfo is not None and net_income is not None and cfo > net_income:
            score += 1

        cur_ltd = _g(cur_bal, "longTermDebt", "long_term_debt") or 0
        prev_ltd = _g(prev_bal, "longTermDebt", "long_term_debt") or 0
        if cur_ltd < prev_ltd:
            score += 1

        cur_ca = _g(cur_bal, "totalCurrentAssets", "total_current_assets")
        cur_cl = _g(cur_bal, "totalCurrentLiabilities", "total_current_liabilities")
        prev_ca = _g(prev_bal, "totalCurrentAssets", "total_current_assets")
        prev_cl = _g(prev_bal, "totalCurrentLiabilities", "total_current_liabilities")
        if cur_ca and cur_cl and prev_ca and prev_cl:
            cr_now = cur_ca / cur_cl
            cr_prev = prev_ca / prev_cl
            if cr_now > cr_prev:
                score += 1

        cur_shares = _g(cur_bal, "commonStock", "common_stock") or _g(cur_bal, "shares")
        prev_shares = _g(prev_bal, "commonStock", "common_stock") or _g(prev_bal, "shares")
        if cur_shares and prev_shares and cur_shares <= prev_shares * 1.001:
            score += 1

        cur_rev = _g(cur_inc, "revenue", "totalRevenue", "total_revenue")
        cur_cogs = _g(cur_inc, "costOfRevenue", "cost_of_revenue")
        prev_rev = _g(prev_inc, "revenue", "totalRevenue", "total_revenue")
        prev_cogs = _g(prev_inc, "costOfRevenue", "cost_of_revenue")
        if cur_rev and cur_cogs is not None and prev_rev and prev_cogs is not None:
            gm_now = (cur_rev - cur_cogs) / cur_rev
            gm_prev = (prev_rev - prev_cogs) / prev_rev
            if gm_now > gm_prev:
                score += 1

        if cur_rev and total_assets and prev_rev and prev_ta:
            at_now = cur_rev / total_assets
            at_prev = prev_rev / prev_ta
            if at_now > at_prev:
                score += 1
    except (TypeError, ZeroDivisionError):
        return None

    return score


# ---------------------------------------------------------------------------
# Altman Z-Score
# ---------------------------------------------------------------------------
def _altman_z(income: dict, balance: dict) -> float | None:
    try:
        wc = (_g(balance, "totalCurrentAssets", "total_current_assets") or 0) - \
             (_g(balance, "totalCurrentLiabilities", "total_current_liabilities") or 0)
        ta = _g(balance, "totalAssets", "total_assets")
        re = _g(balance, "retainedEarnings", "retained_earnings")
        ebit = _g(income, "operatingIncome", "operating_income")
        revenue = _g(income, "revenue", "totalRevenue", "total_revenue")
        equity = _g(balance, "totalStockholdersEquity", "total_stockholders_equity")
        liabilities = _g(balance, "totalLiabilities", "total_liabilities")

        if not ta or ta == 0 or not liabilities:
            return None

        x1 = wc / ta
        x2 = (re or 0) / ta
        x3 = (ebit or 0) / ta
        x4 = ((equity or 0) / liabilities) if liabilities else 0
        x5 = ((revenue or 0) / ta) if ta else 0

        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
        return float(z)
    except (TypeError, ZeroDivisionError):
        return None


# ---------------------------------------------------------------------------
# Beneish M-Score (simplified — needs ≥2 years of data)
# ---------------------------------------------------------------------------
def _beneish_m(income: list[dict], balance: list[dict]) -> float | None:
    # Full Beneish requires 8 indices; this is a defensive simplified version
    # using just DSRI + AQI + GMI + DEPI as a flag, NOT a true M-Score.
    # We return None for now — robust full computation is a Phase 2 enhancement.
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _g(d: dict, *keys: str):
    """Get the first present key from `d`. Tolerates camelCase / snake_case."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None
