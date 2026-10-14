"""Which market to compare a ticker against for relative strength / beta.

Comparing a European ETF or a French bank against the S&P 500 mostly
measures the US-vs-Europe spread, not whether the asset itself is strong,
so each asset gets the index of the market it actually tracks. Bonds and
gold get none — relative strength vs an equity index says nothing useful
about them.
"""

from __future__ import annotations

US = ("SPY", "S&P 500")
EUROPE = ("^STOXX", "STOXX Europe 600")
UK = ("^FTSE", "FTSE 100")
WORLD = ("ACWI", "MSCI ACWI")
EM = ("EEM", "MSCI Emerging Markets")
JAPAN = ("^N225", "Nikkei 225")

_BY_CATEGORY: dict[str, tuple[str, str] | None] = {
    "us_large_cap": US, "us_tech": US,
    "global_developed_em": WORLD, "global_developed": WORLD, "global_dividend": WORLD,
    "factor_quality": WORLD, "factor_value": WORLD, "factor_momentum": WORLD, "factor_low_vol": WORLD,
    "thematic_clean_energy": WORLD, "thematic_automation": WORLD, "thematic_ev": WORLD,
    "europe_developed": EUROPE,
    "emerging_markets": EM,
    "japan": JAPAN,
    "bonds_global": None, "bonds_us_treasury": None, "bonds_eu_govt": None, "bonds_eu_corp": None,
    "commodities_gold": None,
}

_EUROPE_COUNTRIES = {
    "France", "Germany", "Netherlands", "Italy", "Spain", "Belgium", "Ireland", "Austria",
    "Finland", "Portugal", "Greece", "Luxembourg", "Denmark", "Sweden", "Norway",
    "Switzerland", "Poland", "Lithuania", "Latvia", "Estonia",
}


def benchmark_for(
    ticker: str, *, category: str | None = None, country: str | None = None, asset_type: str = "equity",
) -> tuple[str, str] | None:
    """(yahoo_symbol, display_name), or None when relative strength doesn't apply."""
    if category:
        if category.startswith("us_sector"):
            return US
        if category in _BY_CATEGORY:
            return _BY_CATEGORY[category]
    if asset_type == "etf":
        return WORLD
    if country == "United States":
        return US
    if country == "United Kingdom":
        return UK
    if country in _EUROPE_COUNTRIES:
        return EUROPE
    if country == "Japan":
        return JAPAN
    return US if "." not in ticker else WORLD


# Longer-history stand-ins for analog analysis: same exposure, decades of data.
_ANALOG_PROXY: dict[str, tuple[str, str]] = {
    "us_large_cap": ("^GSPC", "S&P 500 index"),
    "us_tech": ("^NDX", "Nasdaq-100 index"),
    "global_developed_em": ("ACWI", "MSCI ACWI (iShares, US-listed)"),
    "global_developed": ("ACWI", "MSCI ACWI (iShares, US-listed)"),
    "global_dividend": ("ACWI", "MSCI ACWI (iShares, US-listed)"),
    "factor_quality": ("ACWI", "MSCI ACWI (iShares, US-listed)"),
    "factor_value": ("ACWI", "MSCI ACWI (iShares, US-listed)"),
    "factor_momentum": ("ACWI", "MSCI ACWI (iShares, US-listed)"),
    "factor_low_vol": ("ACWI", "MSCI ACWI (iShares, US-listed)"),
    "europe_developed": ("^STOXX", "STOXX Europe 600 index"),
    "emerging_markets": ("EEM", "MSCI Emerging Markets (iShares, US-listed)"),
    "japan": ("^N225", "Nikkei 225 index"),
    "us_sector_tech": ("XLK", "US tech sector (XLK)"),
    "us_sector_financials": ("XLF", "US financials sector (XLF)"),
    "us_sector_health": ("XLV", "US health-care sector (XLV)"),
    "us_sector_energy": ("XLE", "US energy sector (XLE)"),
    "us_sector_staples": ("XLP", "US consumer staples sector (XLP)"),
    "us_sector_discretionary": ("XLY", "US consumer discretionary sector (XLY)"),
    "commodities_gold": ("GC=F", "Gold futures"),
    "bonds_us_treasury": ("IEF", "US 7–10y Treasuries (IEF)"),
    "thematic_clean_energy": ("ICLN", "Global clean energy (ICLN)"),
}


def analog_proxy_for(category: str | None) -> tuple[str, str] | None:
    return _ANALOG_PROXY.get(category or "")
