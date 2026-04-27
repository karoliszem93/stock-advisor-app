"""Provider status endpoint — surfaces which data providers are configured,
their rate-limit budgets, and where to get keys for the unconfigured ones.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.providers.registry import provider_status

router = APIRouter()


# Where to obtain each provider's free-tier API key.
PROVIDER_KEY_SOURCES = {
    "yfinance": None,
    "edgar": None,
    "fred": "https://fred.stlouisfed.org/docs/api/api_key.html",
    "alphavantage": "https://www.alphavantage.co/support/#api-key",
    "finnhub": "https://finnhub.io/dashboard",
    "fmp": "https://site.financialmodelingprep.com/developer/docs",
    "simfin": "https://app.simfin.com/account",
    "newsapi": "https://newsapi.org/register",
    "reddit": "https://www.reddit.com/prefs/apps",
}


@router.get("/")
def list_providers_status() -> list[dict]:
    rows = provider_status()
    for r in rows:
        r["key_source_url"] = PROVIDER_KEY_SOURCES.get(r["name"])
    return rows
