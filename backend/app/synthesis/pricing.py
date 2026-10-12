"""Entry / stop-loss / target-price computation + FX conversion helpers.

Sizing logic
------------
We use an ATR-based stop and a timeframe-scaled target. The relative
suggested_risk_pct (% of capital to risk) is fixed by risk profile, with
confidence scaling.

For a Buy:
  entry  = last_close
  stop   = last_close - stop_atr_mult * ATR
  target = last_close + target_atr_mult * ATR

For a Sell-short, signs flip.

Support / resistance refinement (levels from the technical rules engine):
  - Stop: if a support level (resistance for shorts) sits so that a stop just
    beyond it (0.25 ATR) is 0.5–1.5× the ATR stop distance, the stop goes
    there instead — below a real level rather than at an arbitrary distance.
  - Target (1w / 2w / 1m only): if the nearest resistance (support for shorts)
    comes before the ATR target but still leaves ≥ 1.5× reward/risk, the
    target is set just in front of it. If it leaves less, the target is kept
    and a note warns that a level stands in the way.

For an Avoid suggestion, prices are still emitted (for display) but
treated as informational — the user shouldn't act on them.
"""

from __future__ import annotations

from dataclasses import dataclass


# ATR multipliers per timeframe (target distance grows with horizon)
_TARGET_ATR_MULT: dict[str, float] = {
    "1w": 2.0, "2w": 2.5, "1m": 3.5,
    "3m": 5.0, "6m": 7.0, "1y": 10.0, "3y": 15.0,
}
# Stop is roughly half the target distance to give ~2:1 reward/risk
_STOP_ATR_MULT: dict[str, float] = {
    "1w": 1.0, "2w": 1.2, "1m": 1.5,
    "3m": 2.0, "6m": 2.5, "1y": 3.0, "3y": 4.0,
}

# Default % of capital to risk per trade by risk profile
_DEFAULT_RISK_PCT: dict[str, float] = {
    "conservative": 0.005,   # 0.5%
    "balanced":     0.010,   # 1.0%
    "growth":       0.015,   # 1.5%
    "aggressive":   0.025,   # 2.5%
}


@dataclass
class PricedCell:
    direction: str
    currency: str
    entry: float
    stop_loss: float
    target: float
    entry_eur: float | None
    stop_loss_eur: float | None
    target_eur: float | None
    fx_rate_used: float | None
    suggested_risk_pct: float
    notes: list[str]


def price_cell(
    *,
    direction: str,
    last_close: float,
    atr: float | None,
    currency: str,
    timeframe: str,
    risk_profile: str,
    confidence: float,
    macro_bundle: dict | None,
    support: list[float] | None = None,
    resistance: list[float] | None = None,
) -> PricedCell:
    """Compute entry/stop/target prices in native currency + EUR conversion."""
    notes: list[str] = []

    if atr is None or atr <= 0:
        # ATR missing — fall back to a percentage-based stop. Wider notes.
        atr = max(0.01, last_close * 0.02)
        notes.append("ATR unavailable; using 2% of last close as risk unit.")

    target_mult = _TARGET_ATR_MULT.get(timeframe, 3.0)
    stop_mult = _STOP_ATR_MULT.get(timeframe, 1.5)

    if direction == "buy":
        entry = last_close
        stop = last_close - stop_mult * atr
        target = last_close + target_mult * atr
    elif direction == "sell_short":
        entry = last_close
        stop = last_close + stop_mult * atr
        target = last_close - target_mult * atr
    else:
        # avoid: still emit prices for reference
        entry = last_close
        stop = last_close - stop_mult * atr
        target = last_close + target_mult * atr
        notes.append("Direction is 'avoid' — prices are reference only.")

    stop, target = _refine_with_levels(
        direction, entry, stop, target, atr, timeframe, support or [], resistance or [], notes,
    )

    # ---- FX conversion to EUR ----
    fx_rate, fx_note = _fx_to_eur(currency, macro_bundle)
    if fx_note:
        notes.append(fx_note)
    entry_eur = entry * fx_rate if fx_rate else None
    stop_eur = stop * fx_rate if fx_rate else None
    target_eur = target * fx_rate if fx_rate else None

    # ---- Position sizing ----
    base_pct = _DEFAULT_RISK_PCT.get(risk_profile, 0.01)
    # Confidence scaling: clamp [0.5x, 1.5x]
    conf_mult = 0.5 + min(1.0, max(0.0, confidence))
    suggested_pct = base_pct * conf_mult

    return PricedCell(
        direction=direction,
        currency=currency or "",
        entry=round(entry, 4),
        stop_loss=round(stop, 4),
        target=round(target, 4),
        entry_eur=round(entry_eur, 4) if entry_eur is not None else None,
        stop_loss_eur=round(stop_eur, 4) if stop_eur is not None else None,
        target_eur=round(target_eur, 4) if target_eur is not None else None,
        fx_rate_used=round(fx_rate, 6) if fx_rate else None,
        suggested_risk_pct=round(suggested_pct, 5),
        notes=notes,
    )


_SHORT_HORIZONS = {"1w", "2w", "1m"}


def _refine_with_levels(
    direction: str, entry: float, stop: float, target: float, atr: float, timeframe: str,
    support: list[float], resistance: list[float], notes: list[str],
) -> tuple[float, float]:
    """Move stop / target onto nearby support & resistance (see module docstring)."""
    short = direction == "sell_short"
    # levels "behind" the trade protect the stop; levels "ahead" cap the target
    behind = sorted((r for r in resistance if r > entry), key=lambda x: x) if short \
        else sorted((s for s in support if s < entry), key=lambda x: -x)
    ahead = sorted((s for s in support if s < entry), key=lambda x: -x) if short \
        else sorted((r for r in resistance if r > entry), key=lambda x: x)

    atr_stop_dist = abs(entry - stop)
    for lvl in behind:
        cand = lvl + 0.25 * atr if short else lvl - 0.25 * atr
        if 0.5 * atr_stop_dist <= abs(entry - cand) <= 1.5 * atr_stop_dist:
            stop = cand
            notes.append(f"Stop just {'above resistance' if short else 'below support'} at {lvl:.2f}.")
            break

    if ahead:
        lvl = ahead[0]
        risk = abs(entry - stop)
        cand = lvl + 0.1 * atr if short else lvl - 0.1 * atr
        reward = abs(cand - entry)
        before_target = (cand > target) if short else (cand < target)
        if before_target:
            if timeframe in _SHORT_HORIZONS and risk > 0 and reward >= 1.5 * risk:
                target = cand
                notes.append(f"Target just in front of {'support' if short else 'resistance'} at {lvl:.2f}.")
            else:
                notes.append(f"{'Support' if short else 'Resistance'} at {lvl:.2f} lies before the target.")
    return stop, target


def _fx_to_eur(currency: str | None, macro_bundle: dict | None) -> tuple[float | None, str | None]:
    """Convert 1 unit of `currency` to EUR using FRED rates.

    FRED provides:
      DEXUSEU — USD per 1 EUR  (so 1 USD = 1/DEXUSEU EUR)
      DEXUSUK — USD per 1 GBP  (so 1 GBP = DEXUSUK / DEXUSEU EUR)
    """
    if not currency:
        return None, None
    cur = currency.upper()
    if cur == "EUR":
        return 1.0, None
    if not macro_bundle:
        return None, "FX rate unavailable (no FRED macro bundle)."

    usd_per_eur = (macro_bundle.get("DEXUSEU") or {}).get("value")
    if not usd_per_eur or usd_per_eur <= 0:
        return None, "FX USD/EUR rate unavailable."
    eur_per_usd = 1.0 / float(usd_per_eur)

    if cur == "USD":
        return eur_per_usd, None
    if cur == "GBP":
        usd_per_gbp = (macro_bundle.get("DEXUSUK") or {}).get("value")
        if not usd_per_gbp:
            return None, "FX GBP/USD rate unavailable."
        return float(usd_per_gbp) * eur_per_usd, None
    # Other currencies fall through — could add CHF / JPY etc. later
    return None, f"FX conversion for {cur} not implemented."
