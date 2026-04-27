"""Reddit — retail sentiment & mention velocity.

Uses Reddit's OAuth "script" app flow — register an app at
https://www.reddit.com/prefs/apps (type: script). You'll get a client_id
and client_secret; both go in .env.

Subreddits we typically scan:
  stocks, investing, wallstreetbets, SecurityAnalysis, ETFs, dividends

Endpoints (after OAuth):
  POST https://www.reddit.com/api/v1/access_token
  GET  https://oauth.reddit.com/r/{sub}/search?q=...&restrict_sr=1&sort=new&t=week&limit=100
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.providers.base import BaseProvider

log = logging.getLogger(__name__)


class RedditProvider(BaseProvider):
    name = "reddit"
    description = "Reddit — retail mention velocity & sentiment."
    rate_limit_capacity = 1000   # Reddit allows ~60/min for OAuth scripts
    rate_limit_window_seconds = 86400

    AUTH_URL = "https://www.reddit.com/api/v1/access_token"
    OAUTH_BASE = "https://oauth.reddit.com"

    DEFAULT_SUBREDDITS = ("stocks", "investing", "wallstreetbets", "SecurityAnalysis", "ETFs", "dividends")

    def __init__(self, root_data_dir=None):
        super().__init__(root_data_dir)
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    def is_available(self) -> bool:
        s = get_settings()
        return bool(s.reddit_client_id and s.reddit_client_secret)

    def required_key_setting(self) -> str | None:
        return "reddit_client_id"

    # ------------------------------------------------------------------
    def _get_token(self) -> str | None:
        s = get_settings()
        if not (s.reddit_client_id and s.reddit_client_secret):
            return None
        now = datetime.now(timezone.utc)
        if self._token and self._token_expires_at and self._token_expires_at > now + timedelta(seconds=30):
            return self._token

        resp = self.client.post(
            self.AUTH_URL,
            data={"grant_type": "client_credentials"},
            auth=(s.reddit_client_id, s.reddit_client_secret),
            headers={"User-Agent": s.reddit_user_agent},
        )
        resp.raise_for_status()
        blob = resp.json()
        self._token = blob.get("access_token")
        ttl = int(blob.get("expires_in", 3600))
        self._token_expires_at = now + timedelta(seconds=ttl)
        return self._token

    def _oauth_get(self, path: str, params: dict | None = None) -> dict | None:
        s = get_settings()
        token = self._get_token()
        if not token:
            return None
        resp = self.client.get(
            f"{self.OAUTH_BASE}{path}",
            params=params or {},
            headers={"Authorization": f"bearer {token}", "User-Agent": s.reddit_user_agent},
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    def search_ticker(
        self,
        ticker: str,
        subreddits: tuple[str, ...] = DEFAULT_SUBREDDITS,
        time_window: str = "week",
    ) -> list[dict] | None:
        """Return recent posts mentioning the ticker across the given subreddits."""
        cache_key = f"search:{ticker.upper()}:{','.join(subreddits)}:{time_window}"

        def _fetch():
            posts: list[dict] = []
            for sub in subreddits:
                try:
                    data = self._oauth_get(
                        f"/r/{sub}/search",
                        {
                            "q": ticker,
                            "restrict_sr": 1,
                            "sort": "new",
                            "t": time_window,
                            "limit": 50,
                        },
                    ) or {}
                    children = data.get("data", {}).get("children", [])
                    for c in children:
                        d = c.get("data", {})
                        posts.append({
                            "subreddit": d.get("subreddit"),
                            "title": d.get("title"),
                            "selftext": d.get("selftext", "")[:1000],
                            "score": d.get("score", 0),
                            "num_comments": d.get("num_comments", 0),
                            "created_utc": d.get("created_utc"),
                            "permalink": d.get("permalink"),
                        })
                except Exception as exc:  # noqa: BLE001
                    log.debug("Reddit search %s/%s failed: %s", sub, ticker, exc)
            return posts

        return self.cached_request(cache_key, ttl_seconds=3 * 3600, fetch=_fetch)
