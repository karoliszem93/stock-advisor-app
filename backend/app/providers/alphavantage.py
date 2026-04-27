"""Alpha Vantage — fundamentals via REST API.

Free tier is **25 requests/day**, very tight. We cache aggressively (7 days
for fundamentals) and only call this when EDGAR/FMP can't supply what we
need.

Get a key: https://www.alphavantage.co/support/#api-key

Endpoints used:
  ?function=OVERVIEW&symbol=...           Company overview / fundamentals snapshot
  ?function=BALANCE_SHEET&symbol=...
  ?function=INCOME_STATEMENT&symbol=...
  ?function=CASH_FLOW&symbol=...
  ?function=EARNINGS&symbol=...
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.providers.base import BaseProvider

log = logging.getLogger(__name__)


class AlphaVantageProvider(BaseProvider):
    name = "alphavantage"
    description = "Alpha Vantage — fundamentals (free tier 25/day, cache aggressively)."
    rate_limit_capacity = 25
    rate_limit_window_seconds = 86400

    BASE = "https://www.alphavantage.co/query"

    def is_available(self) -> bool:
        return bool(get_settings().alphavantage_api_key)

    def required_key_setting(self) -> str | None:
        return "alphavantage_api_key"

    def _query(self, function: str, symbol: str) -> dict | None:
        s = get_settings()
        if not s.alphavantage_api_key:
            return None
        params = {"function": function, "symbol": symbol.upper(), "apikey": s.alphavantage_api_key}
        data = self.http_get_json(self.BASE, params=params)
        # Alpha Vantage returns a {"Note": "..."} or {"Information": "..."} envelope on rate limit.
        if isinstance(data, dict) and ("Note" in data or "Information" in data):
            log.warning("Alpha Vantage limit hit for %s/%s: %s",
                        function, symbol, data.get("Note") or data.get("Information"))
            return None
        return data

    # ------------------------------------------------------------------
    def get_overview(self, ticker: str) -> dict | None:
        return self.cached_request(
            f"overview:{ticker.upper()}",
            ttl_seconds=7 * 86400,
            fetch=lambda: self._query("OVERVIEW", ticker),
        )

    def get_income_statement(self, ticker: str) -> dict | None:
        return self.cached_request(
            f"income:{ticker.upper()}",
            ttl_seconds=7 * 86400,
            fetch=lambda: self._query("INCOME_STATEMENT", ticker),
        )

    def get_balance_sheet(self, ticker: str) -> dict | None:
        return self.cached_request(
            f"balance:{ticker.upper()}",
            ttl_seconds=7 * 86400,
            fetch=lambda: self._query("BALANCE_SHEET", ticker),
        )

    def get_cash_flow(self, ticker: str) -> dict | None:
        return self.cached_request(
            f"cashflow:{ticker.upper()}",
            ttl_seconds=7 * 86400,
            fetch=lambda: self._query("CASH_FLOW", ticker),
        )

    def get_earnings(self, ticker: str) -> dict | None:
        return self.cached_request(
            f"earnings:{ticker.upper()}",
            ttl_seconds=7 * 86400,
            fetch=lambda: self._query("EARNINGS", ticker),
        )
