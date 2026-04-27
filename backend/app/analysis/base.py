"""Base types + shared helpers for the analysis layer.

Direction vocabulary
--------------------
Modules emit "bullish" / "bearish" / "neutral" — these describe what the
*signal* says, not what the user should do. The buy / avoid / sell_short
decision happens later in synthesis (Phase 3) where risk profile and
position sizing are applied.

ModuleResult
------------
Every module returns the same structured dict. The `raw` field carries
the underlying numbers verbatim into the analysis/<date>/<ticker>.json
file in the data repo, so an agent can later re-derive scores or audit.

AnalysisContext
---------------
A bundle of all provider data for one ticker on one snapshot date. The
pipeline fetches data once per ticker and passes the same context to
every module, guaranteeing a consistent point-in-time view.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

DataQuality = Literal["full", "partial", "missing"]
Direction = Literal["bullish", "bearish", "neutral"]
AssetType = Literal["equity", "etf"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    """Clamp a number into [lo, hi]."""
    return max(lo, min(hi, x))


def direction_from_score(score: float | None, threshold: float = 0.10) -> Direction:
    """Map a [-1, +1] score onto a directional label.

    The threshold guards against tiny edges masquerading as signals — by
    default scores within ±0.10 are reported as neutral.
    """
    if score is None:
        return "neutral"
    if score > threshold:
        return "bullish"
    if score < -threshold:
        return "bearish"
    return "neutral"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class ModuleResult:
    """Structured output of a single analysis module."""

    module: str
    score: float | None = None      # in [-1, +1]; None when data unavailable
    direction: Direction = "neutral"
    confidence: float = 0.0          # in [0, 1]
    horizon_weights: dict[str, float] = field(default_factory=dict)
    # How much this module's signal matters per timeframe, e.g.
    # {"1w": 1.0, "2w": 0.9, "1m": 0.7, "3m": 0.4, "6m": 0.3, "1y": 0.2, "3y": 0.1}.
    # Synthesis combines module scores using these weights.

    raw: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    data_quality: DataQuality = "missing"
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "score": self.score,
            "direction": self.direction,
            "confidence": self.confidence,
            "horizon_weights": self.horizon_weights,
            "raw": self.raw,
            "notes": self.notes,
            "data_quality": self.data_quality,
            "errors": self.errors,
        }


def no_data(module: str, reason: str) -> ModuleResult:
    """Standard 'data unavailable' result — keeps module crash paths uniform."""
    return ModuleResult(
        module=module,
        score=None,
        direction="neutral",
        confidence=0.0,
        data_quality="missing",
        notes=[f"No data available: {reason}"],
    )


# ---------------------------------------------------------------------------
# Context shared across modules
# ---------------------------------------------------------------------------
@dataclass
class AnalysisContext:
    """All provider data for one ticker, fetched once and shared across modules."""

    ticker: str
    asset_type: AssetType
    snapshot_date: date

    # Universe-level metadata (curated ETF entry; watchlist note)
    metadata: dict | None = None

    # Price + volume time series (yfinance get_ohlcv)
    ohlcv: dict | None = None  # {"ticker", "currency", "bars": [...]}

    # Basic descriptive info (yfinance get_info) — unifies equity + ETF
    info: dict | None = None

    # Equity fundamentals — combined view from FMP / Alpha Vantage / EDGAR / SimFin
    fundamentals: dict | None = None

    # ETF-specific snapshot
    etf_info: dict | None = None

    # News headlines (Finnhub + NewsAPI), each may carry sentiment
    news: list[dict] | None = None

    # Social posts (Reddit), enriched with score/comments/age
    social: list[dict] | None = None

    # Macro bundle from FRED — global, same for every ticker on a given run
    macro: dict | None = None

    # Insider summary (EDGAR Form 4 + Finnhub insider transactions)
    insider: dict | None = None

    # Upcoming events (Finnhub earnings calendar, ex-div dates)
    upcoming_events: dict | None = None

    # Reference series for relative-strength comparisons
    benchmark_ohlcv: dict | None = None
    sector_ohlcv: dict | None = None

    # Per-source error log for the run: {"fmp": "rate_limited", ...}
    errors: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------
class BaseAnalysisModule(ABC):
    """Abstract base class for all analysis modules."""

    #: short identifier used in output JSON keys
    name: str = "base"
    #: which asset types this module handles
    applies_to: tuple[AssetType, ...] = ("equity", "etf")
    #: short human-readable description
    description: str = ""

    def applies(self, ctx: AnalysisContext) -> bool:
        return ctx.asset_type in self.applies_to

    @abstractmethod
    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        """Compute the signal. Implementations must be pure functions of
        the context — no side effects, no provider calls, no mutation
        of ctx."""
        ...
