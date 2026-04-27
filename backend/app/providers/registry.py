"""Provider registry — single point of access for all data providers.

Importing this module registers every provider. To use a provider:

    from app.providers.registry import get_provider
    yf = get_provider("yfinance")

Use `provider_status()` to get a list of all providers and their state
(used by the /api/providers endpoint and the Settings page).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.providers.base import BaseProvider

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _registry() -> dict[str, BaseProvider]:
    """Lazy-build the registry. Imports are deferred so optional deps don't
    break startup if a provider's library isn't installed yet.
    """
    from app.providers.alphavantage import AlphaVantageProvider
    from app.providers.edgar import EdgarProvider
    from app.providers.finnhub import FinnhubProvider
    from app.providers.fmp import FmpProvider
    from app.providers.fred import FredProvider
    from app.providers.newsapi import NewsApiProvider
    from app.providers.reddit import RedditProvider
    from app.providers.simfin import SimFinProvider
    from app.providers.yfinance_provider import YFinanceProvider

    instances: list[BaseProvider] = [
        YFinanceProvider(),
        EdgarProvider(),
        FredProvider(),
        AlphaVantageProvider(),
        FinnhubProvider(),
        FmpProvider(),
        SimFinProvider(),
        NewsApiProvider(),
        RedditProvider(),
    ]
    return {p.name: p for p in instances}


def get_provider(name: str) -> BaseProvider:
    reg = _registry()
    if name not in reg:
        raise KeyError(f"Unknown provider: {name}. Available: {sorted(reg)}")
    return reg[name]


def list_providers() -> list[str]:
    return sorted(_registry().keys())


def provider_status() -> list[dict]:
    out = []
    for name in list_providers():
        try:
            out.append(_registry()[name].status())
        except Exception as exc:  # noqa: BLE001
            out.append({"name": name, "error": repr(exc), "available": False})
    return out
