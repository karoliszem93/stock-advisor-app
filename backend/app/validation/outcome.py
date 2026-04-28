"""Outcome computation for a single suggestion.

Given a Suggestion row and the relevant price/dividend/FX history, compute:
  - price return (native currency)
  - dividend return (native currency)
  - FX effect (vs EUR)
  - total return in EUR (gross)
  - estimated after-tax return in EUR (LT-resident assumptions)
  - max favorable / adverse excursion
  - target_hit / stop_hit flags
  - outcome label: correct | incorrect | partial
  - outcome_score in [-1, +1]

Conventions:
  - All returns are decimals (0.05 == +5%).
  - For "buy" suggestions, gains in price are favourable; for "sell_short",
    losses in price are favourable.
  - For "avoid" suggestions, we score the *absence of action* — a small
    realized return either direction is mildly positive (we correctly
    flagged uncertainty), a large move missed is mildly negative.

LT tax simplification:
  - Capital gains tax 15% applied to positive gross_return only.
  - Dividend withholding 15% on dividends.
  - €500 annual exemption is NOT modeled per-trade (we don't track
    yearly aggregate at this layer; UI/reporting can apply it).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable


@dataclass
class OutcomeResult:
    outcome: str                  # correct | incorrect | partial
    outcome_score: float          # in [-1, +1]
    price_return_pct_native: float | None
    dividend_return_pct_native: float | None
    fx_effect_pct_eur: float | None
    total_return_pct_eur: float | None
    after_tax_return_pct_eur: float | None
    max_favorable_excursion_pct: float | None
    max_adverse_excursion_pct: float | None
    target_hit: bool | None
    stop_hit: bool | None
    notes: list[str]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def compute_outcome(
    *,
    direction: str,
    entry_native: float | None,
    stop_native: float | None,
    target_native: float | None,
    bars_in_window: list[dict],
    dividends_in_window: list[dict],
    currency: str,
    fx_rate_at_entry: float | None,
    fx_rate_at_exit: float | None,
    lt_capital_gains_rate: float = 0.15,
    lt_dividend_tax_rate: float = 0.15,
) -> OutcomeResult:
    """Compute the structured outcome for one suggestion.

    `bars_in_window` is a list of OHLCV dicts ordered by date, INCLUSIVE of
    the entry date (open ≈ entry) and inclusive of the target date (close
    is the exit price).
    """
    notes: list[str] = []

    if not bars_in_window or entry_native is None:
        return OutcomeResult(
            outcome="incorrect",
            outcome_score=-1.0 if direction in ("buy", "sell_short") else 0.0,
            price_return_pct_native=None,
            dividend_return_pct_native=None,
            fx_effect_pct_eur=None,
            total_return_pct_eur=None,
            after_tax_return_pct_eur=None,
            max_favorable_excursion_pct=None,
            max_adverse_excursion_pct=None,
            target_hit=None,
            stop_hit=None,
            notes=["No price data in window — outcome cannot be computed."],
        )

    exit_close = float(bars_in_window[-1].get("adj_close")
                       or bars_in_window[-1].get("close"))
    price_ret_native = (exit_close - entry_native) / entry_native if entry_native else 0.0

    # ---- dividends ----
    div_total_native = sum(float(d.get("amount", 0)) for d in (dividends_in_window or []))
    div_ret_native = (div_total_native / entry_native) if entry_native else 0.0

    # ---- target / stop hits ----
    target_hit = None
    stop_hit = None
    if target_native is not None and stop_native is not None:
        if direction == "buy":
            target_hit = any(_high(b) >= target_native for b in bars_in_window)
            stop_hit = any(_low(b) <= stop_native for b in bars_in_window)
        elif direction == "sell_short":
            target_hit = any(_low(b) <= target_native for b in bars_in_window)
            stop_hit = any(_high(b) >= stop_native for b in bars_in_window)

    # ---- excursions (max favorable / adverse vs entry) ----
    if direction == "buy":
        favorable = max((_high(b) - entry_native) / entry_native for b in bars_in_window)
        adverse = min((_low(b) - entry_native) / entry_native for b in bars_in_window)
    elif direction == "sell_short":
        favorable = max((entry_native - _low(b)) / entry_native for b in bars_in_window)
        adverse = min((entry_native - _high(b)) / entry_native for b in bars_in_window)
    else:  # avoid — both directions are "adverse" since we said don't act
        favorable = max((_high(b) - entry_native) / entry_native for b in bars_in_window)
        adverse = min((_low(b) - entry_native) / entry_native for b in bars_in_window)

    # ---- FX effect (only for non-EUR base currency) ----
    fx_effect = None
    if (currency or "").upper() != "EUR" and fx_rate_at_entry and fx_rate_at_exit:
        # Gain/loss purely from FX, ignoring price movement
        fx_effect = (fx_rate_at_exit - fx_rate_at_entry) / fx_rate_at_entry
    # ---- EUR totals ----
    if (currency or "").upper() == "EUR":
        total_eur = price_ret_native + div_ret_native
    elif fx_rate_at_entry and fx_rate_at_exit:
        # Convert each native return to EUR-equivalent and sum
        # Simpler: total_native * (fx_exit / fx_entry) → EUR-denominated return ≈
        total_native = price_ret_native + div_ret_native
        total_eur = (1 + total_native) * (fx_rate_at_exit / fx_rate_at_entry) - 1
    else:
        total_eur = None
        notes.append("FX rate(s) unavailable — total return in EUR not computed.")

    # ---- After-tax return (LT defaults) ----
    after_tax = None
    if total_eur is not None:
        # Tax both legs separately so withholding rate on dividends works correctly
        cg_tax = max(0.0, price_ret_native) * lt_capital_gains_rate
        if (currency or "").upper() != "EUR" and fx_rate_at_entry and fx_rate_at_exit:
            # crude: scale CG tax to EUR via mid-window FX
            cg_tax *= (fx_rate_at_exit + fx_rate_at_entry) / 2 / fx_rate_at_entry
        div_tax = max(0.0, div_ret_native) * lt_dividend_tax_rate
        after_tax = total_eur - cg_tax - div_tax

    # ---- Outcome label & score ----
    outcome, score = _label_outcome(
        direction=direction,
        target_hit=target_hit,
        stop_hit=stop_hit,
        price_ret_native=price_ret_native,
    )

    return OutcomeResult(
        outcome=outcome,
        outcome_score=score,
        price_return_pct_native=round(price_ret_native, 4),
        dividend_return_pct_native=round(div_ret_native, 4),
        fx_effect_pct_eur=round(fx_effect, 4) if fx_effect is not None else None,
        total_return_pct_eur=round(total_eur, 4) if total_eur is not None else None,
        after_tax_return_pct_eur=round(after_tax, 4) if after_tax is not None else None,
        max_favorable_excursion_pct=round(favorable, 4),
        max_adverse_excursion_pct=round(adverse, 4),
        target_hit=target_hit,
        stop_hit=stop_hit,
        notes=notes,
    )


def _label_outcome(
    *, direction: str,
    target_hit: bool | None,
    stop_hit: bool | None,
    price_ret_native: float,
) -> tuple[str, float]:
    """Map (direction, what happened) to (outcome, score)."""
    # Score scales price return ×5 — i.e. ±20% maps to ±1.0
    if direction == "buy":
        score = max(-1.0, min(1.0, price_ret_native * 5))
        if target_hit and not stop_hit:
            return "correct", score
        if stop_hit and not target_hit:
            return "incorrect", score
        if price_ret_native > 0.02:
            return "correct", score
        if price_ret_native < -0.02:
            return "incorrect", score
        return "partial", score

    if direction == "sell_short":
        score = max(-1.0, min(1.0, -price_ret_native * 5))
        if target_hit and not stop_hit:
            return "correct", score
        if stop_hit and not target_hit:
            return "incorrect", score
        if price_ret_native < -0.02:
            return "correct", score
        if price_ret_native > 0.02:
            return "incorrect", score
        return "partial", score

    # Avoid — small realized move is good (we correctly flagged uncertainty),
    # large move missed in either direction is mildly negative.
    abs_ret = abs(price_ret_native)
    if abs_ret < 0.02:
        return "correct", 0.5
    if abs_ret < 0.05:
        return "partial", 0.0
    # Big move we didn't catch — score is negative regardless of direction
    return "incorrect", -min(1.0, abs_ret * 3)


def _high(bar: dict) -> float:
    return float(bar.get("high") or bar.get("adj_close") or bar.get("close") or 0)


def _low(bar: dict) -> float:
    return float(bar.get("low") or bar.get("adj_close") or bar.get("close") or 0)


# ---------------------------------------------------------------------------
# Helper for sweep: bucket bars / dividends by window
# ---------------------------------------------------------------------------
def filter_window(items: Iterable[dict], start: date, end: date, key: str = "date") -> list[dict]:
    """Pick items where item[key] is in [start, end] (inclusive)."""
    out = []
    for it in items:
        d = it.get(key)
        if not d:
            continue
        try:
            if isinstance(d, str):
                ed = date.fromisoformat(d)
            elif isinstance(d, date):
                ed = d
            else:
                continue
        except (TypeError, ValueError):
            continue
        if start <= ed <= end:
            out.append(it)
    return out
