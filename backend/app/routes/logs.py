"""Live log feed for the dashboard — recent backend log lines from memory."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.log_buffer import buffer

router = APIRouter()


@router.get("/")
def recent_logs(
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict:
    """Log lines with id > `after` (oldest first). Poll with the last id you saw.

    `last_id` is the newest id in the buffer; if it's lower than `after`, the
    backend restarted and the client should start over from 0.
    """
    lines, newest = buffer.since(after, limit)
    return {"lines": lines, "last_id": newest}
