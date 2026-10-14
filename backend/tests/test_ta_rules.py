"""Tests for the technical-analysis rules engine (app/analysis/ta)."""

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.analysis.ta import indicators as ind
from app.analysis.ta import rules as ta
from app.synthesis.pricing import price_cell


def _bars(closes, *, volumes=None, opens=None, highs=None, lows=None):
    start = date(2022, 1, 3)
    out = []
    for i, c in enumerate(closes):
        o = opens[i] if opens else c * 0.998
        out.append({
            "date": (start + timedelta(days=i)).isoformat(),
            "open": o,
            "high": highs[i] if highs else max(o, c) * 1.005,
            "low": lows[i] if lows else min(o, c) * 0.995,
            "close": c,
            "volume": volumes[i] if volumes else 1_000_000,
        })
    return out


def _wavy(n=600, seed=1):
    rng = np.random.default_rng(seed)
    p, out = 100.0, []
    for i in range(n):
        p *= 1 + 0.0004 + 0.012 * math.sin(i / 9) * 0.3 + rng.normal(0, 0.01)
        out.append(p)
    vols = [int(1e6 * (1 + rng.random() * (4 if i % 37 == 0 else 1))) for i in range(n)]
    return _bars(out, volumes=vols)


# ---------------------------------------------------------------------------
# indicator math matches the reference `ta` library (Wilder smoothing)
# ---------------------------------------------------------------------------
def test_wilder_indicators_match_ta_library():
    ta_lib = pytest.importorskip("ta")
    df = ta.build_frame(_wavy(400), "date")
    c = df["close"]
    assert ind.rsi(c, 14).iloc[-1] == pytest.approx(ta_lib.momentum.RSIIndicator(c, 14).rsi().iloc[-1], rel=1e-6)
    assert ind.atr(df, 14).iloc[-1] == pytest.approx(
        ta_lib.volatility.AverageTrueRange(df["high"], df["low"], c, 14).average_true_range().iloc[-1], rel=1e-3)
    m = ind.macd(c)
    assert m["macd"].iloc[-1] == pytest.approx(ta_lib.trend.MACD(c).macd().iloc[-1], rel=1e-6)


# ---------------------------------------------------------------------------
# no look-ahead: signals up to bar k never change when later bars arrive
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cut", [250, 380, 470])
def test_no_lookahead_in_any_rule(cut):
    bars = _wavy(520)
    full = ta.evaluate(ta.build_frame(bars, "date"))
    part = ta.evaluate(ta.build_frame(bars[:cut], "date"))
    for rid, out in part.items():
        early = [(e["i"], e["side"], e["label"]) for e in out.events]
        later = [(e["i"], e["side"], e["label"]) for e in full[rid].events if e["i"] < cut]
        assert early == later, f"{rid} changed past signals when future bars were added"


def test_every_rule_reports_status():
    outs = ta.evaluate(ta.build_frame(_wavy(400), "date"))
    assert set(outs) >= set(ta.TECHNICAL_RULES) | set(ta.MEAN_REVERSION_RULES)
    for o in outs.values():
        assert o.status, o.id
        assert -1 <= o.score <= 1


# ---------------------------------------------------------------------------
# specific detections
# ---------------------------------------------------------------------------
def test_volume_confirmed_breakout_detected_and_unconfirmed_ignored():
    closes = [100 + 0.3 * math.sin(i) for i in range(60)] + [104.0]
    vols = [1_000_000] * 60 + [3_000_000]
    out = ta.evaluate(ta.build_frame(_bars(closes, volumes=vols), "date"))["breakout"]
    assert out.events and out.events[-1] == {"i": 60, "side": "buy", "label": "Breakout"}
    assert out.score == pytest.approx(0.20)

    quiet = ta.evaluate(ta.build_frame(_bars(closes, volumes=[1_000_000] * 61), "date"))["breakout"]
    assert not [e for e in quiet.events if e["i"] == 60]


def test_bullish_engulfing_after_decline():
    closes = [110 - i * 0.8 for i in range(40)]           # steady decline
    opens = [c + 0.3 for c in closes]
    closes[-1], opens[-1] = closes[-2] + 1.6, closes[-2] - 0.6   # big green bar engulfing the prior red one
    highs = [max(o, c) + 0.2 for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) - 0.2 for o, c in zip(opens, closes, strict=True)]
    out = ta.evaluate(ta.build_frame(_bars(closes, opens=opens, highs=highs, lows=lows), "date"))["candles"]
    assert any(e["i"] == 39 and e["label"] == "Bullish engulfing" for e in out.events)
    assert out.score > 0


def test_double_bottom_confirmed_on_neckline_break():
    # down to ~90, rally to ~100 (neckline), back to ~90, then break above 100
    path = (list(np.linspace(110, 90, 25)) + list(np.linspace(90, 100, 12)) + list(np.linspace(100, 90.3, 12))
            + list(np.linspace(90.3, 103, 14)))
    out = ta.evaluate(ta.build_frame(_bars(path), "date"))["chart_patterns"]
    db = [e for e in out.events if e["label"] == "Double bottom"]
    assert db, "double bottom not detected"
    assert path[db[0]["i"]] > 100  # confirmed only after the neckline break


# ---------------------------------------------------------------------------
# pricing uses support / resistance
# ---------------------------------------------------------------------------
def test_stop_moves_below_nearby_support():
    p = price_cell(direction="buy", last_close=100, atr=2, currency="EUR", timeframe="1m",
                   risk_profile="balanced", confidence=0.6, macro_bundle=None, support=[98.0], resistance=[])
    # ATR stop would be 97.0; support at 98 -> stop at 98 - 0.25*ATR = 97.5
    assert p.stop_loss == pytest.approx(97.5)
    assert any("below support" in n for n in p.notes)


def test_short_horizon_target_capped_at_resistance():
    p = price_cell(direction="buy", last_close=100, atr=2, currency="EUR", timeframe="1w",
                   risk_profile="balanced", confidence=0.6, macro_bundle=None, support=[], resistance=[103.5])
    # ATR target 104; resistance 103.5 still gives >= 1.5R (risk 2) -> target 103.3
    assert p.target == pytest.approx(103.3)


def test_far_support_is_ignored():
    p = price_cell(direction="buy", last_close=100, atr=2, currency="EUR", timeframe="1m",
                   risk_profile="balanced", confidence=0.6, macro_bundle=None, support=[80.0], resistance=[])
    assert p.stop_loss == pytest.approx(97.0)  # plain ATR stop


def test_serialize_uses_bar_times_and_window():
    df = ta.build_frame(_wavy(300), "date")
    out = ta.serialize(ta.evaluate(df), list(df["time"]), start=200)
    times = set(df["time"].iloc[200:])
    assert all(e["time"] in times for e in out["events"])
    line = next(o for o in out["overlays"]["trend_ema200"] if o["type"] == "line")
    assert line["data"][0]["time"] >= df["time"].iloc[200]
    assert isinstance(pd.Timestamp(line["data"][0]["time"]), pd.Timestamp)


def test_signal_track_record_uses_forward_prices():
    df = ta.build_frame(_wavy(400), "date")
    out = ta.serialize(ta.evaluate(df), list(df["time"]), start=100, closes=df["close"].to_numpy(float))
    closes = df["close"].to_numpy(float)
    idx = {t: i for i, t in enumerate(df["time"])}
    for e in out["events"]:
        i = idx[e["time"]]
        assert e["price"] == pytest.approx(closes[i])
        if i + 20 < len(closes):
            assert e["ret_20"] == pytest.approx(closes[i + 20] / closes[i] - 1)
        else:
            assert e["ret_20"] is None  # too recent to judge
    macd = next(r for r in out["rules"] if r["id"] == "macd")
    buys = [e for e in out["events"] if e["rule"] == "macd" and e["side"] == "buy" and e["ret_20"] is not None]
    assert macd["stats"]["buy"]["n_eval_20"] == len(buys)
    if buys:
        assert macd["stats"]["buy"]["win_20"] == pytest.approx(sum(e["ret_20"] > 0 for e in buys) / len(buys))
    assert 0 <= out["base_rate"]["up_20"] <= 1


# ---------------------------------------------------------------------------
# similar-situation (analog) analysis
# ---------------------------------------------------------------------------
from app.analysis.ta import analogs  # noqa: E402


def test_fingerprints_have_no_lookahead():
    bars = _wavy(900)
    full = analogs.fingerprints(ta.build_frame(bars, "date"))
    part = analogs.fingerprints(ta.build_frame(bars[:700], "date"))
    pd.testing.assert_frame_equal(part.iloc[:700], full.iloc[:700], check_exact=False, rtol=1e-9)


def test_analogs_outcomes_gap_and_exclusion():
    bars = _wavy(1500, seed=3)
    df = ta.build_frame(bars, "date")
    out = analogs.find_analogs(df, k=15)
    assert out["available"]
    closes = df["close"].to_numpy(float)
    pos = {t: i for i, t in enumerate(df["time"])}
    picked = sorted(pos[m["time"]] for m in out["matches"])
    assert all(b - a >= analogs.MIN_GAP for a, b in zip(picked, picked[1:], strict=False))
    assert max(picked) < len(df) - 1 - analogs.EXCLUDE_RECENT
    for m in out["matches"]:
        i = pos[m["time"]]
        if m["ret_20"] is not None:
            assert m["ret_20"] == pytest.approx(closes[i + 20] / closes[i] - 1)
    s = out["summary"]["20"]["analogs"]
    assert s["n"] == sum(m["ret_20"] is not None for m in out["matches"])


def test_analogs_accept_external_fingerprint():
    df = ta.build_frame(_wavy(1500, seed=4), "date")
    today = analogs.today_fingerprint(ta.build_frame(_wavy(900, seed=5), "date"))
    out = analogs.find_analogs(df, k=10, today=today)
    assert out["available"] and out["today"]["rsi"] == pytest.approx(today["rsi"])
