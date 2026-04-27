"""Analysis registry — instantiates every module and runs the applicable
ones for a given ticker.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.analysis.base import AnalysisContext, BaseAnalysisModule, ModuleResult

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _modules() -> list[BaseAnalysisModule]:
    """Lazy module construction — keeps imports cheap when only running one."""
    from app.analysis.etf_fundamental import EtfFundamentalModule
    from app.analysis.event_awareness import EventAwarenessModule
    from app.analysis.fundamental_equity import FundamentalEquityModule
    from app.analysis.insider_institutional import InsiderInstitutionalModule
    from app.analysis.macro import MacroModule
    from app.analysis.mean_reversion import MeanReversionModule
    from app.analysis.momentum import MomentumModule
    from app.analysis.news_sentiment import NewsSentimentModule
    from app.analysis.quality import QualityModule
    from app.analysis.risk_metrics import RiskMetricsModule
    from app.analysis.social_sentiment import SocialSentimentModule
    from app.analysis.technical import TechnicalModule
    from app.analysis.volatility_regime import VolatilityRegimeModule

    return [
        TechnicalModule(),
        MomentumModule(),
        MeanReversionModule(),
        VolatilityRegimeModule(),
        RiskMetricsModule(),
        FundamentalEquityModule(),
        EtfFundamentalModule(),
        QualityModule(),
        NewsSentimentModule(),
        SocialSentimentModule(),
        InsiderInstitutionalModule(),
        MacroModule(),
        EventAwarenessModule(),
    ]


def list_modules() -> list[str]:
    return [m.name for m in _modules()]


def analyze_ticker(ctx: AnalysisContext) -> dict[str, ModuleResult]:
    """Run every applicable module against the context. Never raises —
    a module that crashes is surfaced as a result with `data_quality=missing`
    and an error message captured.
    """
    results: dict[str, ModuleResult] = {}
    for mod in _modules():
        if not mod.applies(ctx):
            continue
        try:
            results[mod.name] = mod.analyze(ctx)
        except Exception as exc:  # noqa: BLE001
            log.exception("Module %s crashed on %s", mod.name, ctx.ticker)
            results[mod.name] = ModuleResult(
                module=mod.name,
                score=None,
                direction="neutral",
                confidence=0.0,
                data_quality="missing",
                errors=[repr(exc)],
                notes=[f"Module crashed: {exc!r}"],
            )
    return results
