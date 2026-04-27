"""Data providers — uniform interface around each external data source.

Every provider subclasses BaseProvider and gets:
  - File-based caching with TTL (no repeat hits on the same key in one run)
  - Per-provider rate limiting (so we stay under free-tier limits)
  - Graceful no-key handling — if the user hasn't configured a key yet,
    is_available() returns False and the pipeline falls back to other sources.

Use the registry to get a provider by name:

    from app.providers.registry import get_provider
    yf = get_provider("yfinance")
    bars = yf.get_ohlcv("AAPL", lookback_days=400)

Each provider documents its rate limits and primary endpoints in its module
docstring.
"""

from app.providers.base import BaseProvider
from app.providers.registry import (
    get_provider,
    list_providers,
    provider_status,
)

__all__ = ["BaseProvider", "get_provider", "list_providers", "provider_status"]
