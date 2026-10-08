"""In-memory ring buffer of recent log records, served to the UI's live log panel.

Holds the last MAX_RECORDS records since the backend started. Each record
gets a monotonically increasing id so the frontend can poll for "everything
after id N" without missing or repeating lines.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections import deque
from datetime import datetime, timezone

from app.redact import redact

MAX_RECORDS = 2000

# Request logs from the UI's own polling would drown everything else out.
_IGNORED_LOGGERS = ("uvicorn.access",)


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = MAX_RECORDS) -> None:
        super().__init__(level=logging.INFO)
        self._records: deque[dict] = deque(maxlen=capacity)
        self._ids = itertools.count(1)
        self._lock_ = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_IGNORED_LOGGERS):
            return
        try:
            msg = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                msg += f" — {record.exc_info[0].__name__}: {record.exc_info[1]}"
            entry = {
                "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "msg": redact(msg)[:1000],
            }
        except Exception:  # noqa: BLE001
            self.handleError(record)
            return
        with self._lock_:
            entry["id"] = next(self._ids)
            self._records.append(entry)

    def since(self, after: int, limit: int) -> tuple[list[dict], int]:
        """Records with id > `after` (newest `limit`), plus the newest id held."""
        with self._lock_:
            new = [r for r in self._records if r["id"] > after]
            newest = self._records[-1]["id"] if self._records else 0
        return new[-limit:], newest


buffer = RingBufferHandler()


def install() -> None:
    """Attach the buffer to the root logger (idempotent)."""
    root = logging.getLogger()
    if buffer not in root.handlers:
        root.addHandler(buffer)
