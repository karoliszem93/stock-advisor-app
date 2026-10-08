"""GDELT DOC 2.0 — average news tone for a search query (free, no key).

GDELT scores every article it indexes (global, multilingual) for tone, roughly
-10 (very negative) .. +10 (very positive); typical news sits within ±3. We ask
for the daily average-tone timeline over the lookback window and summarise it.

GDELT is best-effort: it states a limit of one request per 5 seconds, but in
practice refuses ~half of requests even at 10-20s spacing, and answers slowly.
So calls are serialised with a 10s gap, made once (no retry), and a
per-session budget keeps it from stretching the daily run:
  - after MAX_CONSECUTIVE_429 refusals in a row, or
  - after SESSION_BUDGET_SECONDS of GDELT time,
further calls are skipped until SESSION_RESET_SECONDS of inactivity (i.e. the
next run). Successful results are cached for 36h, so what one day's run
fetches carries over and coverage fills in across runs.
"""

from __future__ import annotations

import threading
import time

from app.providers.base import BaseProvider

MIN_GAP_SECONDS = 10.0
MAX_CONSECUTIVE_429 = 4
SESSION_BUDGET_SECONDS = 8 * 60
SESSION_RESET_SECONDS = 30 * 60


class GdeltBudgetExhausted(RuntimeError):
    pass


class GdeltProvider(BaseProvider):
    name = "gdelt"
    description = "GDELT — global news tone per company / ETF theme (no key; best-effort, heavily rate-limited)."
    rate_limit_capacity = 2000  # self-imposed; the real constraint is GDELT's throttling
    rate_limit_window_seconds = 86400

    URL = "https://api.gdeltproject.org/api/v2/doc/doc"
    _lock = threading.Lock()
    _last_call = 0.0
    _session_start = 0.0
    _consecutive_429 = 0

    def _get(self, params: dict):
        cls = GdeltProvider
        with cls._lock:
            now = time.monotonic()
            if now - cls._last_call > SESSION_RESET_SECONDS:
                cls._session_start, cls._consecutive_429 = now, 0
            if cls._consecutive_429 >= MAX_CONSECUTIVE_429:
                raise GdeltBudgetExhausted(f"skipped — GDELT refused {cls._consecutive_429} requests in a row")
            if now - cls._session_start > SESSION_BUDGET_SECONDS:
                raise GdeltBudgetExhausted("skipped — GDELT time budget for this run used up")

            wait = MIN_GAP_SECONDS - (now - cls._last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.client.get(self.URL, params=params, timeout=30)
            finally:
                cls._last_call = time.monotonic()
            cls._consecutive_429 = cls._consecutive_429 + 1 if resp.status_code == 429 else 0
            resp.raise_for_status()
            return resp

    def get_tone(self, query: str, days: int = 14) -> dict | None:
        """{"avg_tone", "recent_tone" (last 3 days), "days_with_coverage"} or None if no coverage."""
        # GDELT needs OR-ed terms wrapped in parentheses
        q = f"({query})" if " OR " in query else query
        cache_key = f"tone:{q.lower()}:{days}"

        def _fetch():
            resp = self._get({"query": q, "mode": "timelinetone", "timespan": f"{days}d", "format": "json"})
            if not resp.text.strip().startswith("{"):
                # GDELT answers malformed / too-short queries with a plain-text message
                raise ValueError(resp.text.strip()[:150])
            series = (resp.json().get("timeline") or [{}])[0].get("data") or []
            values = [float(p["value"]) for p in series if p.get("value") not in (None, 0)]
            if not values:
                return None
            recent = values[-3:]
            return {
                "avg_tone": sum(values) / len(values),
                "recent_tone": sum(recent) / len(recent),
                "days_with_coverage": len(values),
            }

        return self.cached_request(cache_key, ttl_seconds=36 * 3600, fetch=_fetch)
