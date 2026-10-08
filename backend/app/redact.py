"""Strip credentials from text before it is stored, logged, or sent to an LLM.

Provider HTTP errors embed the full request URL — including `apikey=` /
`token=` query params — in their message, so every `repr(exc)` that leaves
the process has to go through `redact()`.
"""

from __future__ import annotations

import logging
import re

_QUERY_SECRET = re.compile(
    r"([?&](?:api_?key|apikey|token|access_?key|key|secret)=)[^&\s'\"]+",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE)


def redact(text: str) -> str:
    text = _QUERY_SECRET.sub(r"\1***", text)
    return _BEARER.sub(r"\1***", text)


def redact_exc(exc: BaseException, limit: int | None = None) -> str:
    """`repr(exc)` with credentials removed, optionally truncated."""
    out = redact(repr(exc))
    return out[:limit] if limit else out


class RedactingFormatter(logging.Formatter):
    """Log formatter that redacts the fully formatted line, tracebacks included."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))
