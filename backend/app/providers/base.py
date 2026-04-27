"""BaseProvider — abstract base class shared by every data provider."""

from __future__ import annotations

import logging
from abc import ABC
from pathlib import Path
from typing import Any, Callable

import httpx

from app.config import get_settings
from app.providers.cache import FileCache
from app.providers.rate_limiter import RateLimiter, RateLimitError

log = logging.getLogger("app.providers")


class BaseProvider(ABC):
    """Subclass and override `name` plus the data methods you need.

    Subclasses are responsible for:
      - Returning False from `is_available()` when their key is missing.
      - Documenting their rate limit (capacity, window) and passing it
        when constructing the limiter.
      - Using `self.cached_request(...)` to wrap calls that should be
        cached + rate-limited.
    """

    #: short stable identifier used in cache namespacing and the registry
    name: str = "base"
    #: human-readable description, surfaced in the UI
    description: str = ""

    #: free-tier rate limit. Subclasses override these.
    rate_limit_capacity: int = 1_000_000  # effectively unlimited by default
    rate_limit_window_seconds: int = 86400

    def __init__(self, root_data_dir: Path | None = None):
        s = get_settings()
        root = root_data_dir or Path(s.sqlite_path).parent
        root.mkdir(parents=True, exist_ok=True)
        self.cache = FileCache(root, namespace=self.name)
        self.limiter = RateLimiter(
            root,
            namespace=self.name,
            capacity=self.rate_limit_capacity,
            window_seconds=self.rate_limit_window_seconds,
        )
        self.client = httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            headers={"User-Agent": s.sec_edgar_user_agent},
        )

    def __del__(self):
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Methods subclasses typically override
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """Return True if this provider can be queried right now."""
        return True

    def required_key_setting(self) -> str | None:
        """Name of the settings field that must be set for this provider, if any."""
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def cached_request(
        self,
        cache_key: str,
        ttl_seconds: int,
        fetch: Callable[[], Any],
        *,
        respect_rate_limit: bool = True,
    ) -> Any:
        """Run `fetch` only if the cache is empty/expired.

        Always counts against the rate limit when an actual fetch happens.
        Cache hits do not count.
        """
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        if respect_rate_limit:
            try:
                self.limiter.acquire(wait=False)
            except RateLimitError:
                # Re-raise — the caller (analysis pipeline) should catch and
                # mark this signal as degraded.
                raise

        data = fetch()
        if data is not None:
            self.cache.set(cache_key, data, ttl_seconds=ttl_seconds)
        return data

    def http_get_json(self, url: str, params: dict | None = None) -> Any:
        """GET + json with consistent error handling. Raises on non-2xx."""
        resp = self.client.get(url, params=params or {})
        resp.raise_for_status()
        return resp.json()

    def status(self) -> dict:
        out = {
            "name": self.name,
            "description": self.description,
            "available": False,
            "key_setting": self.required_key_setting(),
            "key_present": False,
            "rate_limit": self.limiter.status(),
        }
        try:
            out["available"] = self.is_available()
        except Exception as exc:  # noqa: BLE001
            out["error"] = repr(exc)

        key_field = self.required_key_setting()
        if key_field:
            value = getattr(get_settings(), key_field, None)
            out["key_present"] = bool(value)
        else:
            out["key_present"] = True  # provider needs no key
        return out
