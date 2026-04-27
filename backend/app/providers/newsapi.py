"""NewsAPI.org — generic news search, dev tier 100/day.

This is a supplementary source — Finnhub's company-news is more direct.
NewsAPI is useful when we want broader-context queries (e.g. macro themes,
sector news) rather than per-ticker.

Get a key: https://newsapi.org/register

Endpoint:
  https://newsapi.org/v2/everything?q=...&from=...&to=...&language=en
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from app.config import get_settings
from app.providers.base import BaseProvider

log = logging.getLogger(__name__)


class NewsApiProvider(BaseProvider):
    name = "newsapi"
    description = "NewsAPI.org — generic news search (dev tier 100/day)."
    rate_limit_capacity = 100
    rate_limit_window_seconds = 86400

    BASE = "https://newsapi.org/v2"

    def is_available(self) -> bool:
        return bool(get_settings().newsapi_api_key)

    def required_key_setting(self) -> str | None:
        return "newsapi_api_key"

    def _query(self, path: str, params: dict) -> dict | None:
        s = get_settings()
        if not s.newsapi_api_key:
            return None
        full_params = dict(params)
        full_params["apiKey"] = s.newsapi_api_key
        return self.http_get_json(f"{self.BASE}{path}", params=full_params)

    # ------------------------------------------------------------------
    def search_everything(self, query: str, days: int = 7, language: str = "en") -> list[dict] | None:
        cache_key = f"every:{query.lower()}:{days}:{language}"

        def _fetch():
            today = date.today()
            params = {
                "q": query,
                "from": (today - timedelta(days=days)).isoformat(),
                "to": today.isoformat(),
                "language": language,
                "sortBy": "publishedAt",
                "pageSize": 50,
            }
            data = self._query("/everything", params) or {}
            return data.get("articles", [])

        return self.cached_request(cache_key, ttl_seconds=3600, fetch=_fetch)
