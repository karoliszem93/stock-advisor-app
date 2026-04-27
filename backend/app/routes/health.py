"""Healthcheck and meta routes — used by the frontend to verify connectivity."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app import __version__
from app.config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict:
    s = get_settings()
    has_pat = s.github_token() is not None
    return {
        "status": "ok",
        "version": __version__,
        "now_utc": datetime.now(timezone.utc).isoformat(),
        "timezone": s.timezone,
        "schedule": f"{s.schedule_hour:02d}:{s.schedule_minute:02d} {s.timezone} (Mon-Fri)",
        "config": {
            "base_currency": s.base_currency,
            "github_pat_present": has_pat,
            "ollama_host": s.ollama_host,
            "ollama_model": s.ollama_model,
            "providers_with_keys": _provider_status(s),
        },
    }


def _provider_status(s) -> dict[str, bool]:
    return {
        "alphavantage": bool(s.alphavantage_api_key),
        "finnhub": bool(s.finnhub_api_key),
        "fmp": bool(s.fmp_api_key),
        "simfin": bool(s.simfin_api_key),
        "newsapi": bool(s.newsapi_api_key),
        "fred": bool(s.fred_api_key),
        "reddit": bool(s.reddit_client_id and s.reddit_client_secret),
    }
