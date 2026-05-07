"""Top-level synthesis orchestrator.

Connects:  snapshot → analyze → score per cell → thesis → persist Suggestion rows.

Public entry point:
    generate_suggestions(snapshot_date, db) -> RunSummary

Run flow
--------
1. Build per-run context (macro bundle + benchmark bars).
2. Resolve universe (watchlist + curated ETFs).
3. For each ticker:
     - build AnalysisContext (snapshot)
     - run all applicable analysis modules
4. For each (risk × timeframe) cell:
     - score every analyzed ticker
     - rank and pick top N (>=3 buys + 1 sell_short when available)
5. For each unique ticker that appears in any top-cell:
     - generate ONE base thesis via Ollama
6. For each (top candidate, base thesis) pair:
     - adapt thesis for the cell
     - compute prices (entry/stop/target in native + EUR)
     - build a Suggestion ORM row
     - persist
7. Return a RunSummary so the caller can write to RunLog and/or
   trigger the data-repo commit (Phase 6).

Failure handling: any provider error per-ticker lands in ctx.errors and
flows through to suggestion.rationale.data_quality. Any LLM failure for
a ticker falls back to template-based rationale (still useful but flagged).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session

from app.analysis.base import AnalysisContext, ModuleResult
from app.analysis.registry import analyze_ticker
from app.models import Suggestion
from app.services.snapshot import (
    build_benchmark_ohlcv,
    build_macro_context,
    build_ticker_context,
)
from app.services.universe import UniverseEntry, resolve_universe
from app.synthesis.llm import get_llm_client
from app.synthesis.pricing import price_cell
from app.synthesis.scorer import Candidate, score_candidate, top_n_per_cell
from app.synthesis.thesis import BaseThesis, adapt_thesis_for_cell, generate_base_thesis
from app.synthesis.weights import RISK_PROFILES, TIMEFRAMES, timeframe_to_target_date

log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    snapshot_date: date
    universe_size: int
    tickers_analyzed: int
    suggestions_created: int
    cells: int
    llm_calls: int
    fallbacks: int
    errors: dict[str, str] = field(default_factory=dict)
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------
def generate_suggestions(
    snapshot_date: date,
    db: Session,
    *,
    universe: list[UniverseEntry] | None = None,
    delete_existing_for_tickers: list[str] | None = None,
) -> RunSummary:
    """Run the synthesis pipeline for one snapshot date.

    Optional `universe` param — when given, restricts the run to those
    entries instead of the watchlist + curated ETFs default. Used by the
    single-ticker pipeline.

    Optional `delete_existing_for_tickers` — if set, deletes any existing
    Suggestion rows for those tickers on this snapshot_date before running.
    Prevents duplicates on re-run.
    """
    import time
    started = time.time()

    if delete_existing_for_tickers:
        for ticker in delete_existing_for_tickers:
            db.execute(
                sa_delete(Suggestion).where(
                    Suggestion.ticker == ticker.upper(),
                    Suggestion.suggestion_date == snapshot_date,
                )
            )
        db.commit()

    log.info("synthesis: building per-run context")
    macro = build_macro_context()
    benchmark_ohlcv = build_benchmark_ohlcv("SPY")

    if universe is None:
        universe = resolve_universe(db)
    log.info("synthesis: universe size=%d", len(universe))

    # ---- 1. Snapshot + analysis per ticker ----
    analyses: dict[str, tuple[AnalysisContext, dict[str, ModuleResult]]] = {}
    for entry in universe:
        try:
            ctx = build_ticker_context(
                entry, snapshot_date, macro=macro, benchmark_ohlcv=benchmark_ohlcv,
            )
            results = analyze_ticker(ctx)
            analyses[entry.ticker] = (ctx, results)
        except Exception as exc:  # noqa: BLE001
            log.exception("snapshot/analysis failed for %s", entry.ticker)
            # Skip this ticker; don't poison the rest of the run.
    log.info("synthesis: analyzed %d/%d tickers", len(analyses), len(universe))

    # ---- 2. Score every cell ----
    cell_candidates: dict[tuple[str, str], list[Candidate]] = {}
    for risk in RISK_PROFILES:
        for tf in TIMEFRAMES:
            candidates: list[Candidate] = []
            for ticker, (ctx, results) in analyses.items():
                candidates.append(score_candidate(
                    ticker=ticker,
                    asset_type=ctx.asset_type,
                    risk_profile=risk,
                    timeframe=tf,
                    module_results=results,
                ))
            cell_candidates[(risk, tf)] = top_n_per_cell(candidates, max_total=8)

    # ---- 3. Generate base theses (LLM, one per unique ticker) ----
    unique_tickers = {c.ticker for cell in cell_candidates.values() for c in cell}
    log.info("synthesis: %d unique tickers across all cells; calling LLM", len(unique_tickers))

    client = get_llm_client()
    available, message = client.is_available()
    log.info("LLM client: %s — %s", type(client).__name__, message)
    if not available:
        log.warning("LLM not available (%s) — all theses will use template fallback", message)

    from app.config import get_settings
    import time as _time
    settings = get_settings()
    inter_call = float(getattr(settings, "llm_inter_call_delay_seconds", 0.0) or 0.0)

    base_theses: dict[str, BaseThesis] = {}
    llm_calls = 0
    fallbacks = 0
    last_call_at = 0.0
    for i, ticker in enumerate(sorted(unique_tickers), 1):
        ctx, results = analyses[ticker]

        # Rate-limit: if we're still inside the inter-call window, sleep.
        if available and inter_call > 0 and last_call_at > 0:
            elapsed = _time.time() - last_call_at
            if elapsed < inter_call:
                _time.sleep(inter_call - elapsed)

        log.info("LLM (%d/%d) — %s", i, len(unique_tickers), ticker)
        try:
            thesis = generate_base_thesis(ctx, results, client=client if available else None)
            base_theses[ticker] = thesis
            if thesis.model and thesis.model != "(fallback)":
                llm_calls += 1
            else:
                fallbacks += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("thesis generation failed for %s", ticker)
            fallbacks += 1
        last_call_at = _time.time()

    # ---- 4. Build & persist Suggestion rows ----
    created = 0
    cells = 0
    for (risk, tf), candidates in cell_candidates.items():
        cells += 1
        for cand in candidates:
            base = base_theses.get(cand.ticker)
            if base is None:
                continue  # unable to even build a fallback
            row = _build_suggestion_row(
                cand=cand,
                base=base,
                snapshot_date=snapshot_date,
                ctx=analyses[cand.ticker][0],
                results=analyses[cand.ticker][1],
                macro=macro,
            )
            db.add(row)
            created += 1
    db.commit()

    summary = RunSummary(
        snapshot_date=snapshot_date,
        universe_size=len(universe),
        tickers_analyzed=len(analyses),
        suggestions_created=created,
        cells=cells,
        llm_calls=llm_calls,
        fallbacks=fallbacks,
        errors={},
        duration_seconds=round(time.time() - started, 1),
    )
    log.info(
        "synthesis: complete in %ss — %d suggestions across %d cells (LLM=%d fallback=%d)",
        summary.duration_seconds, created, cells, llm_calls, fallbacks,
    )
    return summary


# ---------------------------------------------------------------------------
# Suggestion row builder
# ---------------------------------------------------------------------------
def _build_suggestion_row(
    *,
    cand: Candidate,
    base: BaseThesis,
    snapshot_date: date,
    ctx: AnalysisContext,
    results: dict[str, ModuleResult],
    macro: dict | None,
) -> Suggestion:
    """Build (but don't persist) a Suggestion ORM row from a scored candidate."""
    # Resolve last close + ATR from the technical module's raw output
    technical_raw = (results.get("technical") or _empty_result()).raw or {}
    last_close = technical_raw.get("last_close")
    atr = technical_raw.get("atr_14")
    currency = (ctx.ohlcv or {}).get("currency") or (ctx.info or {}).get("currency") or ""

    if last_close is None:
        # No price data — emit a degraded suggestion with NULL prices
        priced = None
    else:
        priced = price_cell(
            direction=cand.direction,
            last_close=float(last_close),
            atr=float(atr) if atr else None,
            currency=currency,
            timeframe=cand.timeframe,
            risk_profile=cand.risk_profile,
            confidence=cand.cell_confidence,
            macro_bundle=macro,
        )

    rationale = adapt_thesis_for_cell(base, cand)
    if priced and priced.notes:
        rationale.setdefault("price_notes", []).extend(priced.notes)

    target_date = timeframe_to_target_date(snapshot_date, cand.timeframe)

    return Suggestion(
        suggestion_date=snapshot_date,
        ticker=cand.ticker,
        asset_type=cand.asset_type,
        timeframe=cand.timeframe,
        risk_profile=cand.risk_profile,
        direction=cand.direction,
        confidence=cand.cell_confidence,
        confidence_calibrated=None,    # set by Phase 4 calibration
        target_date=target_date,
        entry_price_eur=priced.entry_eur if priced else None,
        stop_loss_eur=priced.stop_loss_eur if priced else None,
        target_price_eur=priced.target_eur if priced else None,
        suggested_risk_pct=priced.suggested_risk_pct if priced else None,
        headline=rationale.get("headline"),
        rationale=rationale,
        # Pointers — populated by Phase 6 once the data-repo commit lands.
        data_repo_commit_sha=None,
        suggestion_json_path=None,
        analysis_json_path=None,
    )


def _empty_result() -> ModuleResult:
    return ModuleResult(module="empty")
