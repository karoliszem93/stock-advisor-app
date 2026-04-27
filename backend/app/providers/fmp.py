"""Financial Modeling Prep — fundamentals, ratios, key metrics.

Uses FMP's "Stable" API (post-2024 migration). The legacy /api/v3/... paths
are paid-only for accounts created after the migration; /stable/... is the
new free-tier surface.

Free tier: 250 requests/day, 5/sec.

Get a key: https://site.financialmodelingprep.com/developer/docs

Endpoints used (all under /stable):
  /stable/profile?symbol=...
  /stable/key-metrics-ttm?symbol=...
  /stable/ratios-ttm?symbol=...
  /stable/income-statement?symbol=...&limit=5
  /stable/balance-sheet-statement?symbol=...&limit=5
  /stable/cash-flow-statement?symbol=...&limit=5
  /stable/etf-info?symbol=...                  (ETF info: domicile, expense ratio, AUM)
  /stable/etf-holdings?symbol=...              (ETF holdings)
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.providers.base import BaseProvider

log = logging.getLogger(__name__)


class FmpProvider(BaseProvider):
    name = "fmp"
    description = "Financial Modeling Prep — fundamentals, ratios, ETF info (free 250/day, /stable API)."
    rate_limit_capacity = 250
    rate_limit_window_seconds = 86400

    BASE = "https://financialmodelingprep.com/stable"

    def is_available(self) -> bool:
        return bool(get_settings().fmp_api_key)

    def required_key_setting(self) -> str | None:
        return "fmp_api_key"

    def _query(self, path: str, params: dict | None = None) -> list | dict | None:
        s = get_settings()
        if not s.fmp_api_key:
            return None
        full_params = dict(params or {})
        full_params["apikey"] = s.fmp_api_key
        return self.http_get_json(f"{self.BASE}{path}", params=full_params)

    @staticmethod
    def _first(data) -> dict | None:
        """FMP often returns a single-element list. Normalize."""
        if isinstance(data, list):
            return data[0] if data else None
        if isinstance(data, dict):
            return data
        return None

    # ------------------------------------------------------------------
    def get_profile(self, ticker: str) -> dict | None:
        return self.cached_request(
            f"profile:{ticker.upper()}",
            ttl_seconds=7 * 86400,
            fetch=lambda: self._first(self._query("/profile", {"symbol": ticker.upper()})),
        )

    def get_key_metrics_ttm(self, ticker: str) -> dict | None:
        return self.cached_request(
            f"key_metrics_ttm:{ticker.upper()}",
            ttl_seconds=7 * 86400,
            fetch=lambda: self._first(self._query("/key-metrics-ttm", {"symbol": ticker.upper()})),
        )

    def get_ratios_ttm(self, ticker: str) -> dict | None:
        return self.cached_request(
            f"ratios_ttm:{ticker.upper()}",
            ttl_seconds=7 * 86400,
            fetch=lambda: self._first(self._query("/ratios-ttm", {"symbol": ticker.upper()})),
        )

    def get_income_statement(self, ticker: str, periods: int = 5) -> list[dict] | None:
        return self.cached_request(
            f"income:{ticker.upper()}:{periods}",
            ttl_seconds=7 * 86400,
            fetch=lambda: self._query(
                "/income-statement", {"symbol": ticker.upper(), "limit": periods}
            ) or [],
        )

    def get_balance_sheet(self, ticker: str, periods: int = 5) -> list[dict] | None:
        return self.cached_request(
            f"balance:{ticker.upper()}:{periods}",
            ttl_seconds=7 * 86400,
            fetch=lambda: self._query(
                "/balance-sheet-statement", {"symbol": ticker.upper(), "limit": periods}
            ) or [],
        )

    def get_cash_flow(self, ticker: str, periods: int = 5) -> list[dict] | None:
        return self.cached_request(
            f"cashflow:{ticker.upper()}:{periods}",
            ttl_seconds=7 * 86400,
            fetch=lambda: self._query(
                "/cash-flow-statement", {"symbol": ticker.upper(), "limit": periods}
            ) or [],
        )

    # ----- ETF-specific -----
    def get_etf_info(self, ticker: str) -> dict | None:
        """Domicile, expense ratio, AUM — critical for LT tax annotations."""
        return self.cached_request(
            f"etf_info:{ticker.upper()}",
            ttl_seconds=14 * 86400,
            fetch=lambda: self._first(self._query("/etf-info", {"symbol": ticker.upper()})),
        )

    def get_etf_holdings(self, ticker: str) -> list[dict] | None:
        return self.cached_request(
            f"etf_holdings:{ticker.upper()}",
            ttl_seconds=30 * 86400,
            fetch=lambda: self._query("/etf-holdings", {"symbol": ticker.upper()}) or [],
        )
