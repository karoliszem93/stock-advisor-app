"""FINRA consolidated short interest — US listings only (free, no key).

Published twice a month (mid-month and month-end settlement dates). Gives
the short position, its change vs the previous report, and days-to-cover.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.providers.base import BaseProvider


class FinraProvider(BaseProvider):
    name = "finra"
    description = "FINRA — US short interest, twice monthly (no key)."
    rate_limit_capacity = 1000
    rate_limit_window_seconds = 86400

    URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"

    def get_short_interest(self, ticker: str) -> dict | None:
        cache_key = f"short_interest:{ticker.upper()}"

        def _fetch():
            today = date.today()
            resp = self.client.post(self.URL, headers={"Accept": "application/json"}, json={
                "limit": 10,
                "compareFilters": [
                    {"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": ticker.upper()},
                ],
                # reports are twice monthly; 60 days always includes the latest one
                "dateRangeFilters": [{
                    "fieldName": "settlementDate",
                    "startDate": (today - timedelta(days=60)).isoformat(),
                    "endDate": today.isoformat(),
                }],
            })
            resp.raise_for_status()
            rows = resp.json() if resp.content else []
            if not rows:
                return None
            r = max(rows, key=lambda x: x.get("settlementDate") or "")
            cur = r.get("currentShortPositionQuantity")
            prev = r.get("previousShortPositionQuantity")
            return {
                "settlement_date": r.get("settlementDate"),
                "short_shares": cur,
                "short_change_pct": ((cur - prev) / prev) if cur is not None and prev else None,
                "days_to_cover": r.get("daysToCoverQuantity"),
            }

        return self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch)
