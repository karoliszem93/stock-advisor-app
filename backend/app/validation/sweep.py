"""Validation sweep — find suggestions whose target_date has passed and
score them.

Runs as part of the morning pipeline before the new day's analysis. For
each due suggestion:
  1. Fetch OHLCV from suggestion_date through target_date (yfinance).
  2. Pick out dividend events in the window.
  3. Resolve FX rates at entry and exit if currency != EUR.
  4. Call compute_outcome(...) to score it.
  5. Persist a SuggestionValidation row.

Returns a SweepSummary with counts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Suggestion, SuggestionValidation
from app.providers.registry import get_provider
from app.validation.outcome import compute_outcome, filter_window

log = logging.getLogger(__name__)


@dataclass
class SweepSummary:
    sweep_date: date
    candidates: int = 0
    validated: int = 0
    skipped: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    new_validations: list[int] = field(default_factory=list)


def sweep_due_validations(db: Session, *, today: date | None = None) -> SweepSummary:
    today = today or date.today()
    summary = SweepSummary(sweep_date=today)
    s = get_settings()

    # Find suggestions whose target_date has arrived and don't yet have a validation
    due = db.scalars(
        select(Suggestion)
        .outerjoin(SuggestionValidation)
        .where(
            Suggestion.target_date <= today,
            SuggestionValidation.id.is_(None),
        )
        .order_by(Suggestion.target_date.asc())
    ).all()
    summary.candidates = len(due)
    log.info("validation sweep: %d due suggestions", len(due))

    if not due:
        return summary

    yfinance = get_provider("yfinance")
    fred = get_provider("fred")

    # Cache per-ticker price + dividend pulls so multiple suggestions on the
    # same ticker reuse one fetch.
    ohlcv_cache: dict[str, dict | None] = {}
    div_cache: dict[str, list[dict] | None] = {}

    # FRED FX bundle once — assumes EUR base.
    macro_bundle = None
    try:
        macro_bundle = fred.get_macro_bundle() if fred.is_available() else None
    except Exception as exc:  # noqa: BLE001
        summary.errors["fred"] = repr(exc)[:200]

    # We need rolling FX context. For simplicity v1: use current (most-recent)
    # rate as both entry and exit FX. A future iteration can fetch the precise
    # historical rate for each suggestion's entry and exit dates.
    usd_eur_now = ((macro_bundle or {}).get("DEXUSEU") or {}).get("value")
    gbp_usd_now = ((macro_bundle or {}).get("DEXUSUK") or {}).get("value")

    for sug in due:
        try:
            v_row = _validate_one(
                sug=sug,
                yfinance=yfinance,
                ohlcv_cache=ohlcv_cache,
                div_cache=div_cache,
                today=today,
                usd_eur=usd_eur_now,
                gbp_usd=gbp_usd_now,
                lt_cg_rate=s.lt_capital_gains_rate,
                lt_div_rate=s.lt_dividend_tax_rate,
            )
            if v_row is None:
                summary.skipped += 1
                continue
            db.add(v_row)
            db.flush()
            summary.new_validations.append(v_row.id)
            summary.validated += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("validation failed for suggestion %s", sug.id)
            summary.errors[f"sug_{sug.id}"] = repr(exc)[:200]

    db.commit()
    log.info("validation sweep: %d validated, %d skipped, %d errors",
             summary.validated, summary.skipped, len(summary.errors))
    return summary


def _validate_one(
    *,
    sug: Suggestion,
    yfinance,
    ohlcv_cache: dict,
    div_cache: dict,
    today: date,
    usd_eur: float | None,
    gbp_usd: float | None,
    lt_cg_rate: float,
    lt_div_rate: float,
) -> SuggestionValidation | None:
    """Score a single suggestion. Returns None if data is too thin to score."""
    # We need enough history to cover the suggestion's window
    lookback = (today - sug.suggestion_date).days + 30
    cache_key = sug.ticker
    if cache_key not in ohlcv_cache:
        ohlcv_cache[cache_key] = yfinance.get_ohlcv(sug.ticker, lookback_days=lookback)
        div_cache[cache_key] = yfinance.get_dividends(sug.ticker, years=2)
    ohlcv = ohlcv_cache[cache_key] or {}
    bars_all = ohlcv.get("bars") or []
    if not bars_all:
        return None

    # Window inclusive of suggestion_date through min(target_date, today)
    window_end = min(sug.target_date, today)
    bars = filter_window(bars_all, sug.suggestion_date, window_end)
    if len(bars) < 2:
        return None

    dividends = filter_window(div_cache.get(cache_key) or [], sug.suggestion_date, window_end)

    # Resolve native entry/stop/target by reversing EUR→native using the
    # FX rate that was used at suggestion time. We didn't store it — for
    # now reconstruct using the same logic as pricing.py would today.
    currency = ohlcv.get("currency") or ""
    fx_rate_at_entry, fx_rate_at_exit = _resolve_fx(
        currency=currency, usd_eur=usd_eur, gbp_usd=gbp_usd,
    )

    # Approximate native entry from EUR entry × (1/fx_rate). When EUR is base,
    # they're equal. When fx_rate is missing, fall back to the close on
    # suggestion_date.
    entry_native = _native_from_eur(sug.entry_price_eur, fx_rate_at_entry)
    stop_native = _native_from_eur(sug.stop_loss_eur, fx_rate_at_entry)
    target_native = _native_from_eur(sug.target_price_eur, fx_rate_at_entry)
    if entry_native is None:
        entry_native = float(bars[0].get("adj_close") or bars[0].get("close") or 0) or None
    if entry_native is None:
        return None

    out = compute_outcome(
        direction=sug.direction,
        entry_native=entry_native,
        stop_native=stop_native,
        target_native=target_native,
        bars_in_window=bars,
        dividends_in_window=dividends,
        currency=currency,
        fx_rate_at_entry=fx_rate_at_entry,
        fx_rate_at_exit=fx_rate_at_exit,
        lt_capital_gains_rate=lt_cg_rate,
        lt_dividend_tax_rate=lt_div_rate,
    )

    return SuggestionValidation(
        suggestion_id=sug.id,
        validated_at=datetime.now(timezone.utc),
        outcome=out.outcome,
        outcome_score=out.outcome_score,
        actual_price_return_pct=out.price_return_pct_native,
        actual_dividend_return_pct=out.dividend_return_pct_native,
        actual_fx_effect_pct=out.fx_effect_pct_eur,
        actual_total_return_pct_eur=out.total_return_pct_eur,
        after_tax_return_pct_eur=out.after_tax_return_pct_eur,
        max_favorable_excursion_pct=out.max_favorable_excursion_pct,
        max_adverse_excursion_pct=out.max_adverse_excursion_pct,
        target_hit=out.target_hit,
        stop_hit=out.stop_hit,
        notes={
            "narrative": out.notes,
            "currency": currency,
            "window_bars": len(bars),
            "fx_used_entry": fx_rate_at_entry,
            "fx_used_exit": fx_rate_at_exit,
        },
    )


def _resolve_fx(currency: str, usd_eur: float | None, gbp_usd: float | None) -> tuple[float | None, float | None]:
    """Return (fx_rate_at_entry, fx_rate_at_exit) for native→EUR conversion.

    v1 simplification: use the same current rate for both. Future: fetch
    historical FX from FRED for each suggestion's exact entry and exit dates.
    """
    cur = (currency or "").upper()
    if cur == "EUR":
        return 1.0, 1.0
    if cur == "USD" and usd_eur and usd_eur > 0:
        rate = 1.0 / float(usd_eur)
        return rate, rate
    if cur == "GBP" and usd_eur and gbp_usd:
        rate = float(gbp_usd) * (1.0 / float(usd_eur))
        return rate, rate
    return None, None


def _native_from_eur(eur_price: float | None, fx_rate: float | None) -> float | None:
    if eur_price is None:
        return None
    if fx_rate is None or fx_rate == 0:
        return None
    return float(eur_price) / float(fx_rate)
