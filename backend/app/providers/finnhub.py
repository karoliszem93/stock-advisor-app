"""Finnhub — news + sentiment, earnings calendar, recommendation trends.

Free tier: 60 calls/min. Daily cap is loose; we throttle per-minute by
treating it as 60 * 60 * 24 / 60 ≈ 86400/min slots.

Get a key: https://finnhub.io/dashboard

Endpoints used:
  /company-news?symbol=...&from=YYYY-MM-DD&to=YYYY-MM-DD
  /news-sentiment?symbol=...
  /calendar/earnings?from=...&to=...&symbol=...
  /stock/recommendation?symbol=...
  /quote?symbol=...   (current price)
  /stock/insider-transactions?symbol=...&from=...&to=...
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from app.config import get_settings
from app.providers.base import BaseProvider

log = logging.getLogger(__name__)


class FinnhubProvider(BaseProvider):
    name = "finnhub"
    description = "Finnhub — news, sentiment, earnings calendar, recommendations."
    # 60/min rolling — but we drive the pipeline once a day, so daily cap is what matters
    rate_limit_capacity = 50_000
    rate_limit_window_seconds = 86400

    BASE = "https://finnhub.io/api/v1"

    def is_available(self) -> bool:
        return bool(get_settings().finnhub_api_key)

    def required_key_setting(self) -> str | None:
        return "finnhub_api_key"

    def _query(self, path: str, params: dict | None = None) -> dict | list | None:
        s = get_settings()
        if not s.finnhub_api_key:
            return None
        full_params = dict(params or {})
        full_params["token"] = s.finnhub_api_key
        return self.http_get_json(f"{self.BASE}{path}", params=full_params)

    # ------------------------------------------------------------------
    def get_company_news(self, ticker: str, days: int = 14) -> list[dict] | None:
        cache_key = f"news:{ticker.upper()}:{days}"

        def _fetch():
            today = date.today()
            params = {
                "symbol": ticker.upper(),
                "from": (today - timedelta(days=days)).isoformat(),
                "to": today.isoformat(),
            }
            data = self._query("/company-news", params)
            return data or []

        return self.cached_request(cache_key, ttl_seconds=3600, fetch=_fetch)

    def get_news_sentiment(self, ticker: str) -> dict | None:
        return self.cached_request(
            f"sentiment:{ticker.upper()}",
            ttl_seconds=3 * 3600,
            fetch=lambda: self._query("/news-sentiment", {"symbol": ticker.upper()}),
        )

    def get_earnings_calendar(self, ticker: str, days_ahead: int = 90) -> list[dict] | None:
        cache_key = f"earn_cal:{ticker.upper()}:{days_ahead}"

        def _fetch():
            today = date.today()
            params = {
                "symbol": ticker.upper(),
                "from": today.isoformat(),
                "to": (today + timedelta(days=days_ahead)).isoformat(),
            }
            data = self._query("/calendar/earnings", params) or {}
            return data.get("earningsCalendar", [])

        return self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch)

    def get_recommendation_trend(self, ticker: str) -> list[dict] | None:
        return self.cached_request(
            f"reco:{ticker.upper()}",
            ttl_seconds=24 * 3600,
            fetch=lambda: self._query("/stock/recommendation", {"symbol": ticker.upper()}) or [],
        )

    def get_insider_transactions(self, ticker: str, days: int = 90) -> dict | None:
        cache_key = f"insider:{ticker.upper()}:{days}"

        def _fetch():
            today = date.today()
            params = {
                "symbol": ticker.upper(),
                "from": (today - timedelta(days=days)).isoformat(),
                "to": today.isoformat(),
            }
            return self._query("/stock/insider-transactions", params)

        return self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch)
