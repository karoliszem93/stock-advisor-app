"""File-based JSON cache with TTL.

One file per cache key under ``backend/data/cache/<namespace>/<key>.json``.
Caches are intentionally local and not shared across machines — they're a
speed/quota optimization, not a source of truth. The data repo is the
source of truth.

Format:
    {
      "fetched_at": ISO-8601 UTC,
      "ttl_seconds": int,
      "key": "...",
      "data": <provider-specific payload>
    }
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_key(key: str) -> str:
    """Make a cache key safe to use as a filename. Long keys get hashed."""
    cleaned = _SAFE_KEY_RE.sub("_", key)
    if len(cleaned) > 120:
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        cleaned = f"{cleaned[:80]}_{h}"
    return cleaned


class FileCache:
    """Per-namespace file-backed cache."""

    def __init__(self, root: Path, namespace: str):
        self.dir = Path(root) / "cache" / namespace
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / f"{_safe_key(key)}.json"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                blob = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Cache read failed for %s: %s", path, exc)
            return None

        ttl = int(blob.get("ttl_seconds", 0))
        fetched = datetime.fromisoformat(blob["fetched_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > fetched + timedelta(seconds=ttl):
            return None  # expired
        return blob.get("data")

    def set(self, key: str, data: Any, ttl_seconds: int) -> None:
        path = self._path(key)
        blob = {
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "ttl_seconds": int(ttl_seconds),
            "key": key,
            "data": data,
        }
        tmp = path.with_suffix(".json.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(blob, f, ensure_ascii=False, default=str)
            tmp.replace(path)
        except OSError as exc:
            log.warning("Cache write failed for %s: %s", path, exc)
            tmp.unlink(missing_ok=True)

    def evict_expired(self) -> int:
        """Walk the namespace and delete expired entries. Returns count removed."""
        removed = 0
        now = datetime.now(timezone.utc)
        for f in self.dir.glob("*.json"):
            try:
                with f.open("r", encoding="utf-8") as fh:
                    blob = json.load(fh)
                fetched = datetime.fromisoformat(blob["fetched_at"].replace("Z", "+00:00"))
                if now > fetched + timedelta(seconds=int(blob.get("ttl_seconds", 0))):
                    f.unlink()
                    removed += 1
            except (json.JSONDecodeError, OSError, KeyError, ValueError):
                # corrupted entries get removed too
                f.unlink(missing_ok=True)
                removed += 1
        return removed
