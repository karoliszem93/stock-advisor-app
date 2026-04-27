"""Analysis modules — turn provider data into structured signals.

Each module is a class implementing BaseAnalysisModule.analyze(ctx) ->
ModuleResult. Modules are pure (no provider calls of their own); the
pipeline pre-fetches data into AnalysisContext and shares it across
modules so all signals on one ticker derive from a consistent snapshot.

Use:
    from app.analysis.registry import analyze_ticker
    results = analyze_ticker(ctx)   # dict[str, ModuleResult]
"""

from app.analysis.base import (
    AnalysisContext,
    AssetType,
    BaseAnalysisModule,
    DataQuality,
    Direction,
    ModuleResult,
    clamp,
    direction_from_score,
    no_data,
)

__all__ = [
    "AnalysisContext",
    "AssetType",
    "BaseAnalysisModule",
    "DataQuality",
    "Direction",
    "ModuleResult",
    "clamp",
    "direction_from_score",
    "no_data",
]
