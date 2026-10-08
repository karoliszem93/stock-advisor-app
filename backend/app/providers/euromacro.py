"""Euro-area macro — ECB Data Portal, Eurostat and STOXX (all free, no key).

  ECB      deposit facility rate, 10Y AAA govt yield, EUR/USD
  Eurostat euro-area HICP inflation; EU Economic Sentiment Indicator
           (long-term average = 100)
  STOXX    VSTOXX — implied volatility of the Euro Stoxx 50 (Europe's VIX)

Each series is fetched independently; a failure is recorded under its key
and the rest of the bundle still returns.
"""

from __future__ import annotations

import logging
import ssl

import certifi
import httpx

from app.providers.base import BaseProvider
from app.redact import redact_exc

log = logging.getLogger(__name__)

_ECB = "https://data-api.ecb.europa.eu/service/data"
_ECB_SERIES = {
    "ECB_DFR": "FM/D.U2.EUR.4F.KR.DFR.LEV",              # deposit facility rate, %
    "EA_10Y": "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",     # AAA 10Y yield, %
    "EURUSD": "EXR/D.USD.EUR.SP00.A",                    # USD per EUR
}
_EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
# HICP moved to the COICOP-2018 dataset in 2026 (the ECB's ICP series stop at 2025-12)
_EUROSTAT_SERIES = {
    "EA_HICP": ("prc_hicp_minr", {"geo": "EA", "unit": "RCH_A", "coicop18": "TOTAL"}),  # % y/y
    "EU_ESI": ("teibs010", {"geo": "EU27_2020"}),
}
_VSTOXX = "https://www.stoxx.com/document/Indices/Current/HistoricalData/h_v2tx.txt"
# stoxx.com serves an intermediate cross-signed by a root newer OpenSSL no
# longer trusts; this is the same intermediate issued by SSL.com's current root.
_STOXX_INTERMEDIATE = "http://cert.ssl.com/SSL.com-TLS-I-RSA-R1.cer"


class EuroMacroProvider(BaseProvider):
    name = "euromacro"
    description = "ECB + Eurostat + STOXX — euro rates, inflation, sentiment, VSTOXX (no key)."
    rate_limit_capacity = 500
    rate_limit_window_seconds = 86400

    def get_bundle(self) -> dict | None:
        return self.cached_request("bundle", ttl_seconds=12 * 3600, fetch=self._fetch_bundle)

    def _fetch_bundle(self) -> dict:
        out: dict[str, dict] = {}
        for key, path in _ECB_SERIES.items():
            out[key] = self._safe(lambda p=path: self._ecb(p))
        for key, (dataset, params) in _EUROSTAT_SERIES.items():
            out[key] = self._safe(lambda d=dataset, p=params: self._eurostat(d, p))
        out["VSTOXX"] = self._safe(self._vstoxx)
        return out

    @staticmethod
    def _safe(fn) -> dict:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            log.debug("euromacro fetch failed: %s", exc)
            return {"error": redact_exc(exc, 200)}

    # ---- ECB ----
    def _ecb(self, path: str) -> dict:
        resp = self.client.get(f"{_ECB}/{path}", params={"format": "jsondata", "lastNObservations": 70})
        resp.raise_for_status()
        j = resp.json()
        dates = [v["id"] for v in j["structure"]["dimensions"]["observation"][0]["values"]]
        obs = next(iter(j["dataSets"][0]["series"].values()))["observations"]
        points = sorted((dates[int(i)], v[0]) for i, v in obs.items() if v and v[0] is not None)
        # series keys start with the frequency: D(aily), M(onthly), B(usiness daily)
        return _summarise(points, monthly=path.split("/")[1].startswith("M"))

    # ---- Eurostat ----
    def _eurostat(self, dataset: str, params: dict) -> dict:
        resp = self.client.get(f"{_EUROSTAT}/{dataset}", params={**params, "lastTimePeriod": 4})
        resp.raise_for_status()
        j = resp.json()
        times = j["dimension"]["time"]["category"]["index"]  # {"2026-06": 0, ...}
        by_idx = {pos: t for t, pos in times.items()}
        points = sorted((by_idx[int(i)], v) for i, v in j["value"].items())
        return _summarise(points, monthly=True)

    # ---- STOXX ----
    def _vstoxx(self) -> dict:
        ctx = ssl.create_default_context(cafile=certifi.where())
        ctx.load_verify_locations(cadata=self.client.get(_STOXX_INTERMEDIATE).content)
        resp = httpx.get(_VSTOXX, verify=ctx, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        points = []
        for line in resp.text.strip().splitlines()[-30:]:
            parts = line.split(";")
            if len(parts) == 3:
                d, _, v = parts
                try:
                    dd, mm, yyyy = d.split(".")
                    points.append((f"{yyyy}-{mm}-{dd}", float(v)))
                except ValueError:
                    continue  # header line
        return _summarise(sorted(points))


def _summarise(points: list[tuple[str, float]], monthly: bool = False) -> dict:
    """Latest value plus changes over ~1 week and ~3 months.

    Daily series: 5 and 60 observations back. Monthly series: no weekly
    change, 3 observations back for the quarter.
    """
    if not points:
        raise ValueError("no observations")
    date, value = points[-1]

    def back(n: int) -> float:
        return float(points[-n - 1][1]) if len(points) > n else float(points[0][1])

    return {
        "value": float(value),
        "date": date,
        "delta_7d": None if monthly else float(value) - back(5),
        "delta_90d": float(value) - back(3 if monthly else 60),
        "prev": float(points[-2][1]) if len(points) > 1 else None,
    }
