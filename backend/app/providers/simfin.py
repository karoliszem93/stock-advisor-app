"""SimFin — bulk fundamentals snapshots.

SimFin's free tier is best for periodic bulk downloads of all-companies
fundamentals; their per-call API is rate-limited similarly to others. We
treat it as a fallback / cross-check source rather than a primary one.

Get a key: https://app.simfin.com/account

For Phase 1 we only wire the basic per-ticker endpoints. Bulk-download
optimization can be added later if/when the universe grows large enough
to justify it.

Endpoints used:
  https://prod.simfin.com/api/v3/companies?ticker=...
  https://prod.simfin.com/api/v3/companies/statements?ticker=...&statements=PL,BS,CF&period=ttm
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.providers.base import BaseProvider

log = logging.getLogger(__name__)


class SimFinProvider(BaseProvider):
    name = "simfin"
    description = "SimFin — fundamentals (free tier; bulk-friendly)."
    rate_limit_capacity = 1000
    rate_limit_window_seconds = 86400

    BASE = "https://prod.simfin.com/api/v3"

    def is_available(self) -> bool:
        return bool(get_settings().simfin_api_key)

    def required_key_setting(self) -> str | None:
        return "simfin_api_key"

    def _headers(self) -> dict:
        s = get_settings()
        return {"Authorization": f"api-key {s.simfin_api_key}"}

    def _query(self, path: str, params: dict | None = None) -> list | dict | None:
        s = get_settings()
        if not s.simfin_api_key:
            return None
        resp = self.client.get(
            f"{self.BASE}{path}", params=params or {}, headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    def get_company(self, ticker: str) -> dict | None:
        cache_key = f"company:{ticker.upper()}"

        def _fetch():
            data = self._query("/companies", {"ticker": ticker.upper()}) or []
            return data[0] if isinstance(data, list) and data else None

        return self.cached_request(cache_key, ttl_seconds=14 * 86400, fetch=_fetch)

    def get_statements_ttm(self, ticker: str) -> dict | None:
        cache_key = f"statements_ttm:{ticker.upper()}"

        def _fetch():
            return self._query(
                "/companies/statements",
                {"ticker": ticker.upper(), "statements": "PL,BS,CF", "period": "ttm"},
            )

        return self.cached_request(cache_key, ttl_seconds=7 * 86400, fetch=_fetch)
