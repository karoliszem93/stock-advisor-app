"""SEC EDGAR — official US filings, no API key but a User-Agent header is required.

Used for:
  - 10-K / 10-Q / 8-K filings (full-text fundamental analysis)
  - Form 4 (insider transactions)
  - 13F (institutional holdings, quarterly)
  - XBRL company facts (structured fundamentals — best free US fundamentals source)

Endpoints:
  https://data.sec.gov/submissions/CIK<10-digit>.json
  https://data.sec.gov/api/xbrl/companyfacts/CIK<10-digit>.json
  https://data.sec.gov/api/xbrl/companyconcept/CIK<10-digit>/us-gaap/<concept>.json

Rate limit: SEC asks for max 10 req/sec from a given UA. We cap below that.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.providers.base import BaseProvider

log = logging.getLogger(__name__)


class EdgarProvider(BaseProvider):
    name = "edgar"
    description = "SEC EDGAR — US filings + XBRL fundamentals (no key)."
    rate_limit_capacity = 50_000   # SEC allows 10/s; we use a generous daily budget
    rate_limit_window_seconds = 86400

    BASE_DATA = "https://data.sec.gov"

    def __init__(self, root_data_dir=None):
        super().__init__(root_data_dir)
        s = get_settings()
        # SEC requires a contact email in the User-Agent.
        self.client.headers["User-Agent"] = s.sec_edgar_user_agent
        self.client.headers["Accept"] = "application/json"

    def is_available(self) -> bool:
        return True

    def required_key_setting(self) -> str | None:
        return None

    # ------------------------------------------------------------------
    def get_cik(self, ticker: str) -> str | None:
        """Resolve ticker -> 10-digit zero-padded CIK string."""
        cache_key = "ticker_cik_map"

        def _fetch():
            url = "https://www.sec.gov/files/company_tickers.json"
            data = self.http_get_json(url)
            # data is dict keyed by integer indices: {"0": {"cik_str": ..., "ticker": "AAPL", ...}}
            return {entry["ticker"].upper(): str(entry["cik_str"]).zfill(10) for entry in data.values()}

        mapping = self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch) or {}
        return mapping.get(ticker.upper())

    def get_company_facts(self, ticker: str) -> dict | None:
        """Return XBRL company facts (canonical structured fundamentals)."""
        cik = self.get_cik(ticker)
        if cik is None:
            return None
        cache_key = f"company_facts:{cik}"

        def _fetch():
            url = f"{self.BASE_DATA}/api/xbrl/companyfacts/CIK{cik}.json"
            return self.http_get_json(url)

        return self.cached_request(cache_key, ttl_seconds=24 * 3600, fetch=_fetch)

    def get_recent_filings(self, ticker: str, *, forms: tuple[str, ...] = ("10-K", "10-Q", "8-K", "4")) -> list[dict] | None:
        """Recent filings of the given form types. Returns up to ~40 most-recent."""
        cik = self.get_cik(ticker)
        if cik is None:
            return None
        cache_key = f"submissions:{cik}:{','.join(forms)}"

        def _fetch():
            url = f"{self.BASE_DATA}/submissions/CIK{cik}.json"
            data = self.http_get_json(url)
            recent = data.get("filings", {}).get("recent", {})
            forms_list = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            primary_docs = recent.get("primaryDocument", [])
            out = []
            for f, d, acc, doc in zip(forms_list, dates, accessions, primary_docs):
                if f in forms:
                    acc_clean = acc.replace("-", "")
                    out.append({
                        "form": f,
                        "filing_date": d,
                        "accession": acc,
                        "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc}",
                    })
            return out

        return self.cached_request(cache_key, ttl_seconds=12 * 3600, fetch=_fetch)

    def get_insider_form4_summary(self, ticker: str, days: int = 90) -> dict | None:
        """Insider buying/selling summary over the last `days` days from Form 4 filings.

        This is a lightweight summary based on filing counts. Full Form 4 parsing
        (with share counts and dollar values) is a Phase 2 enhancement.
        """
        filings = self.get_recent_filings(ticker, forms=("4",)) or []
        from datetime import date as _date, timedelta as _td

        cutoff = _date.today() - _td(days=days)
        recent = [f for f in filings if _date.fromisoformat(f["filing_date"]) >= cutoff]
        return {
            "ticker": ticker.upper(),
            "lookback_days": days,
            "form4_filings": len(recent),
            "filings": recent[:30],
        }
