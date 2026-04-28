"""Validation-layer tests — outcome math + calibration PAVA."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Suggestion, SuggestionValidation
from app.validation.calibration import (
    MIN_VALIDATIONS_FOR_CALIBRATION,
    _pava,
    fit_calibration,
)
from app.validation.outcome import compute_outcome


# ---------------------------------------------------------------------------
# Outcome math
# ---------------------------------------------------------------------------
def _bar(d: str, o: float, h: float, l: float, c: float) -> dict:
    return {"date": d, "open": o, "high": h, "low": l, "close": c, "adj_close": c, "volume": 1_000_000}


def test_buy_hits_target_correct():
    bars = [
        _bar("2026-04-01", 100, 101, 99, 100),
        _bar("2026-04-15", 105, 110, 104, 108),  # target_hit @ high=110
        _bar("2026-04-30", 109, 112, 108, 110),
    ]
    out = compute_outcome(
        direction="buy",
        entry_native=100.0,
        stop_native=95.0,
        target_native=110.0,
        bars_in_window=bars,
        dividends_in_window=[],
        currency="EUR",
        fx_rate_at_entry=1.0,
        fx_rate_at_exit=1.0,
    )
    assert out.target_hit is True
    assert out.stop_hit is False
    assert out.outcome == "correct"
    assert out.outcome_score > 0
    assert out.price_return_pct_native == pytest.approx(0.10)
    assert out.total_return_pct_eur == pytest.approx(0.10)


def test_buy_hits_stop_incorrect():
    bars = [
        _bar("2026-04-01", 100, 101, 94, 95),  # stop_hit at low=94
        _bar("2026-04-15", 95, 96, 92, 93),
    ]
    out = compute_outcome(
        direction="buy",
        entry_native=100.0,
        stop_native=95.0,
        target_native=110.0,
        bars_in_window=bars,
        dividends_in_window=[],
        currency="EUR",
        fx_rate_at_entry=1.0, fx_rate_at_exit=1.0,
    )
    assert out.stop_hit is True
    assert out.target_hit is False
    assert out.outcome == "incorrect"
    assert out.outcome_score < 0


def test_dividend_adds_to_native_return():
    bars = [_bar("2026-04-01", 100, 100, 100, 100), _bar("2026-04-30", 100, 100, 100, 100)]
    out = compute_outcome(
        direction="buy",
        entry_native=100.0,
        stop_native=95.0, target_native=110.0,
        bars_in_window=bars,
        dividends_in_window=[{"date": "2026-04-15", "amount": 2.0}],
        currency="EUR",
        fx_rate_at_entry=1.0, fx_rate_at_exit=1.0,
    )
    assert out.dividend_return_pct_native == pytest.approx(0.02)
    assert out.total_return_pct_eur == pytest.approx(0.02)


def test_avoid_small_move_is_correct():
    bars = [_bar("2026-04-01", 100, 100, 100, 100), _bar("2026-04-30", 100.5, 101, 99.5, 100.5)]
    out = compute_outcome(
        direction="avoid",
        entry_native=100.0,
        stop_native=None, target_native=None,
        bars_in_window=bars,
        dividends_in_window=[],
        currency="EUR",
        fx_rate_at_entry=1.0, fx_rate_at_exit=1.0,
    )
    assert out.outcome == "correct"
    assert out.outcome_score == 0.5


def test_short_correct_when_price_falls():
    bars = [_bar("2026-04-01", 100, 101, 99, 100), _bar("2026-04-30", 95, 96, 88, 90)]
    out = compute_outcome(
        direction="sell_short",
        entry_native=100.0,
        stop_native=105.0, target_native=90.0,
        bars_in_window=bars,
        dividends_in_window=[],
        currency="EUR",
        fx_rate_at_entry=1.0, fx_rate_at_exit=1.0,
    )
    assert out.target_hit is True
    assert out.outcome == "correct"
    assert out.outcome_score > 0


def test_after_tax_subtracts_lt_rate():
    bars = [_bar("2026-04-01", 100, 101, 99, 100), _bar("2026-04-30", 110, 111, 109, 110)]
    out = compute_outcome(
        direction="buy",
        entry_native=100.0, stop_native=95.0, target_native=120.0,
        bars_in_window=bars, dividends_in_window=[],
        currency="EUR", fx_rate_at_entry=1.0, fx_rate_at_exit=1.0,
        lt_capital_gains_rate=0.15, lt_dividend_tax_rate=0.15,
    )
    # gross 10%, after 15% LT CG → 8.5%
    assert out.after_tax_return_pct_eur == pytest.approx(0.085, abs=0.0001)


# ---------------------------------------------------------------------------
# PAVA / calibration
# ---------------------------------------------------------------------------
def test_pava_monotonicity():
    xs = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    ys = [0.0, 0.5, 0.3, 0.7, 0.4, 0.9, 1.0]   # not monotone
    bps, vals = _pava(xs, ys)
    assert all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))


def test_calibration_skips_below_threshold():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    # Only 5 validations — far below MIN_VALIDATIONS_FOR_CALIBRATION
    for i in range(5):
        s = Suggestion(
            suggestion_date=date(2026, 4, 1),
            ticker="X", asset_type="equity",
            timeframe="1m", risk_profile="balanced",
            direction="buy", confidence=0.5,
            target_date=date(2026, 5, 1),
        )
        db.add(s)
        db.flush()
        from datetime import datetime, timezone
        db.add(SuggestionValidation(
            suggestion_id=s.id,
            validated_at=datetime.now(timezone.utc),
            outcome="correct" if i % 2 == 0 else "incorrect",
            outcome_score=0.1,
        ))
    db.commit()

    model = fit_calibration(db)
    assert model is None
    assert MIN_VALIDATIONS_FOR_CALIBRATION >= 50
