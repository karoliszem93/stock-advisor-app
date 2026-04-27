"""FRED — Federal Reserve Economic Data. Free key, generous rate limit.

Get a key at: https://fred.stlouisfed.org/docs/api/api_key.html

Used for macro context: 10Y rate, VIX, yield curve spread, unemployment,
recession indicators. Each suggestion's macro module reads a small bundle
of these and stamps the values into the analysis JSON.

Series we typically want:
  DGS10            10-Year Treasury rate
  DGS2             2-Year Treasury rate
  T10Y2Y           10Y - 2Y spread (recession proxy)
  VIXCLS           VIX
  UNRATE           Unemployment rate
  DEXUSEU          USD/EUR
  DEXUSUK          USD/GBP
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from app.config import get_settings
from app.providers.base import BaseProvider

log = logging.getLogger(__name__)


class FredProvider(BaseProvider):
    name = "fred"
    description = "Federal Reserve Economic Data — macro indicators, FX, rates."
    rate_limit_capacity = 100_000  # FRED allows ~120 req/min; daily cap is loose
    rate_limit_window_seconds = 86400

    BASE = "https://api.stlouisfed.org/fred"

    def is_available(self) -> bool:
        return bool(get_settings().fred_api_key)

    def required_key_setting(self) -> str | None:
        return "fred_api_key"

    # ------------------------------------------------------------------
    def get_series(self, series_id: str, lookback_days: int = 365) -> list[dict] | None:
        cache_key = f"series:{series_id}:{lookback_days}"

        def _fetch():
            s = get_settings()
            if not s.fred_api_key:
                return None
            start = (date.today() - timedelta(days=lookback_days)).isoformat()
            url = f"{self.BASE}/series/observations"
            params = {
                "series_id": series_id,
                "api_key": s.fred_api_key,
                "file_type": "json",
                "observation_start": start,
            }
            data = self.http_get_json(url, params=params)
            obs = data.get("observations", [])
            out = []
            for o in obs:
                v = o.get("value")
                if v in (None, "", "."):
                    continue
                try:
                    out.append({"date": o["date"], "value": float(v)})
                except ValueError:
                    continue
            return out

        return self.cached_request(cache_key, ttl_seconds=12 * 3600, fetch=_fetch)

    def get_macro_bundle(self) -> dict | None:
        """Convenience: latest values for the macro series we always want."""
        if not self.is_available():
            return None
        ids = ["DGS10", "DGS2", "T10Y2Y", "VIXCLS", "UNRATE", "DEXUSEU", "DEXUSUK"]
        out: dict[str, dict] = {}
        for sid in ids:
            try:
                series = self.get_series(sid, lookback_days=30) or []
                if series:
                    last = series[-1]
                    prev = series[-7] if len(series) > 7 else series[0]
                    out[sid] = {
                        "value": last["value"],
                        "date": last["date"],
                        "delta_7d": last["value"] - prev["value"],
                    }
            except Exception as exc:  # noqa: BLE001
                log.debug("FRED %s failed: %s", sid, exc)
                out[sid] = {"error": repr(exc)}
        return out
