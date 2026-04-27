"""Per-provider sliding-window rate limiter, persistent across restarts.

For free tiers like Alpha Vantage's 25 calls/day, we need a counter that
survives process restarts and rolls over correctly. We track timestamps
of recent calls in a small JSON file per provider.

Concurrency: this app runs single-process, so no inter-process locking is
needed. If we ever multi-process, swap for an SQLite-backed counter.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

log = logging.getLogger(__name__)


class RateLimitError(RuntimeError):
    """Raised when a provider's quota would be exceeded."""


class RateLimiter:
    """Sliding-window rate limiter.

    capacity: max calls allowed in window
    window_seconds: window size, e.g. 86400 for daily
    """

    def __init__(self, root: Path, namespace: str, capacity: int, window_seconds: int):
        self.namespace = namespace
        self.capacity = capacity
        self.window = window_seconds
        self.path = Path(root) / "ratelimit" / f"{namespace}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._calls: deque[float] = deque()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                blob = json.load(f)
            self._calls = deque(float(t) for t in blob.get("calls", []))
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            log.warning("Rate limit state read failed for %s: %s", self.path, exc)

    def _save(self) -> None:
        try:
            with self.path.open("w", encoding="utf-8") as f:
                json.dump({"calls": list(self._calls), "saved_at": time.time()}, f)
        except OSError as exc:
            log.warning("Rate limit state write failed for %s: %s", self.path, exc)

    def _evict_old(self, now: float) -> None:
        cutoff = now - self.window
        while self._calls and self._calls[0] < cutoff:
            self._calls.popleft()

    def acquire(self, *, wait: bool = False) -> None:
        """Reserve one call. Raise RateLimitError if exceeded (or wait=True)."""
        with self._lock:
            now = time.time()
            self._evict_old(now)
            if len(self._calls) >= self.capacity:
                if not wait:
                    oldest = self._calls[0]
                    retry_in = self.window - (now - oldest)
                    raise RateLimitError(
                        f"{self.namespace}: {self.capacity} calls / {self.window}s "
                        f"exhausted; retry in ~{retry_in:.0f}s"
                    )
                # If wait=True, sleep until a slot opens
                sleep_for = self.window - (now - self._calls[0]) + 0.5
                log.info("%s rate-limited; sleeping %.0fs", self.namespace, sleep_for)
                time.sleep(sleep_for)
                now = time.time()
                self._evict_old(now)
            self._calls.append(now)
            self._save()

    def status(self) -> dict:
        with self._lock:
            now = time.time()
            self._evict_old(now)
            used = len(self._calls)
            return {
                "capacity": self.capacity,
                "window_seconds": self.window,
                "used": used,
                "remaining": max(0, self.capacity - used),
                "resets_at": (
                    datetime.fromtimestamp(self._calls[0] + self.window, tz=timezone.utc).isoformat()
                    if self._calls
                    else None
                ),
            }
