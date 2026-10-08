"""Google News RSS — free headline search, no key.

Used where Finnhub's free tier can't help: non-US listings (London/Xetra
ETFs, European equities). Results are returned in Finnhub's company-news
shape ({"headline", "summary", "datetime", "source", "url"}) so the
news_sentiment module consumes them unchanged.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from app.providers.base import BaseProvider


class GoogleNewsProvider(BaseProvider):
    name = "googlenews"
    description = "Google News RSS — headlines for non-US tickers and ETF themes (no key)."
    rate_limit_capacity = 500  # self-imposed politeness cap per day
    rate_limit_window_seconds = 86400

    URL = "https://news.google.com/rss/search"

    def search(self, query: str, days: int = 14, limit: int = 30) -> list[dict] | None:
        cache_key = f"search:{query.lower()}:{days}"

        def _fetch():
            resp = self.client.get(self.URL, params={
                "q": f"{query} when:{days}d",
                "hl": "en-GB", "gl": "GB", "ceid": "GB:en",
            })
            resp.raise_for_status()
            out = []
            for item in ET.fromstring(resp.text).findall(".//item")[:limit]:
                title = item.findtext("title") or ""
                source = item.findtext("source") or ""
                # Google appends " - Publisher" to every title; drop it.
                if source and title.endswith(f" - {source}"):
                    title = title[: -len(source) - 3]
                try:
                    ts = int(parsedate_to_datetime(item.findtext("pubDate") or "").timestamp())
                except (TypeError, ValueError):
                    ts = None
                out.append({
                    "headline": title,
                    "summary": "",
                    "datetime": ts,
                    "source": source,
                    "url": item.findtext("link"),
                })
            return out

        return self.cached_request(cache_key, ttl_seconds=3 * 3600, fetch=_fetch)
