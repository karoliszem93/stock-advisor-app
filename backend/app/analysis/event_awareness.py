"""Event awareness module.

Flags upcoming earnings / ex-div / FOMC dates that fall WITHIN the
suggestion window for each timeframe. Earnings events especially raise
uncertainty — the module returns a small NEGATIVE score adjustment and
sets `confidence_drivers` notes that synthesis weaves into the rationale.

The pipeline pre-resolves the date windows for each timeframe (1w, 2w,
1m, 3m, 6m, 1y, 3y) and stamps them in ctx.upcoming_events so this
module can simply read which events fall where.

Expected ctx.upcoming_events shape:
  {
    "earnings": [{"date": "2026-05-22", "estimate": ..., "fiscal_period": "Q1 2026"}],
    "ex_dividend": [{"date": "2026-05-15", "amount": ...}],
    "fomc": ["2026-05-14"]   # global; only matters as macro context
  }
"""

from __future__ import annotations

from datetime import date, timedelta

from app.analysis.base import (
    AnalysisContext,
    BaseAnalysisModule,
    ModuleResult,
    clamp,
    no_data,
)

# Mapping each timeframe to a number of trading days (approx).
TIMEFRAME_DAYS = {
    "1w": 7, "2w": 14, "1m": 30, "3m": 90,
    "6m": 180, "1y": 365, "3y": 365 * 3,
}


class EventAwarenessModule(BaseAnalysisModule):
    name = "event_awareness"
    description = "Flags earnings / ex-div / FOMC inside each timeframe window."

    HORIZON_WEIGHTS = {tf: 0.5 for tf in TIMEFRAME_DAYS}

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        ev = ctx.upcoming_events or {}
        if not ev:
            r = no_data(self.name, "no upcoming-events data")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        today = ctx.snapshot_date

        per_timeframe: dict[str, dict] = {}
        for tf, days in TIMEFRAME_DAYS.items():
            window_end = today + timedelta(days=days)
            earnings_in = _events_in_window(ev.get("earnings") or [], today, window_end)
            exdiv_in = _events_in_window(ev.get("ex_dividend") or [], today, window_end)
            fomc_in = _date_strings_in_window(ev.get("fomc") or [], today, window_end)
            per_timeframe[tf] = {
                "earnings_in_window": [e["date"] for e in earnings_in],
                "ex_dividend_in_window": [e["date"] for e in exdiv_in],
                "fomc_in_window": fomc_in,
            }

        # Build a global-ish score: small negative if earnings are imminent.
        # Synthesis applies per-timeframe confidence reductions using the raw
        # field below.
        notes: list[str] = []
        score_adj = 0.0
        if per_timeframe.get("1m", {}).get("earnings_in_window"):
            score_adj -= 0.05
            notes.append(
                f"Earnings event(s) within 1m: {per_timeframe['1m']['earnings_in_window']}."
            )
        if per_timeframe.get("3m", {}).get("earnings_in_window"):
            notes.append(
                f"Earnings event(s) within 3m: {per_timeframe['3m']['earnings_in_window']}."
            )

        return ModuleResult(
            module=self.name,
            score=clamp(score_adj, -0.10, 0.10),
            direction="neutral",
            confidence=0.6,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "by_timeframe": per_timeframe,
                "next_earnings": (ev.get("earnings") or [{}])[0].get("date"),
            },
            notes=notes,
            data_quality="full",
        )


def _events_in_window(events: list[dict], start: date, end: date) -> list[dict]:
    out = []
    for e in events:
        d = e.get("date")
        if not d:
            continue
        try:
            ed = date.fromisoformat(d)
        except (TypeError, ValueError):
            continue
        if start <= ed <= end:
            out.append(e)
    return out


def _date_strings_in_window(dates: list[str], start: date, end: date) -> list[str]:
    out = []
    for d in dates:
        try:
            ed = date.fromisoformat(d)
        except (TypeError, ValueError):
            continue
        if start <= ed <= end:
            out.append(d)
    return out
