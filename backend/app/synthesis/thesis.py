"""Thesis generation — turn structured analysis into a written rationale.

Two-tier approach for cost and consistency:

  generate_base_thesis(ticker_summary)
    Calls the LLM ONCE per (ticker, snapshot_date). Produces the canonical
    thesis: technical_case, fundamental_case, sentiment_case, macro_context,
    key_risks, invalidation_triggers, tax_notes — all timeframe-agnostic.

  adapt_thesis_for_cell(base_thesis, candidate)
    Pure-Python (no LLM call) wrapper that adds:
      - headline       per-cell, derived from candidate.direction + ticker
      - why_this_timeframe   templated from cell_score + dominant contributor
      - confidence_drivers   from candidate.contributors and notes

Total LLM calls per run ≈ unique tickers analyzed (≈ universe size), not
per (risk × timeframe) cell. With ~50–100 tickers this typically takes
20–60 minutes on a 14B model — comfortable inside the morning window.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.analysis.base import AnalysisContext, ModuleResult
from app.synthesis.llm import LLMClient, get_llm_client
from app.synthesis.scorer import (
    DIRECTION_THRESHOLD,
    MIN_CONFIDENCE,
    Candidate,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an investment analyst producing structured analysis for a quantitative system. Your reader is an LT-resident retail investor who trades on Trading 212. Be specific, cite numbers from the data provided, and be honest about uncertainty.

You MUST respond with valid JSON conforming exactly to this schema:

{
  "technical_case":   "1-3 sentences citing concrete numbers (RSI, MACD, EMAs, ADX) from the data",
  "fundamental_case": "1-3 sentences citing concrete fundamentals (P/E, ROE, growth) — use 'n/a for ETF' for ETFs",
  "sentiment_case":   "1-2 sentences on news + social sentiment direction; cite numbers if available",
  "macro_context":    "1-2 sentences on how the current macro regime supports or weighs against this thesis",
  "key_risks":        ["risk 1", "risk 2", "risk 3"],
  "invalidation_triggers": ["trigger 1", "trigger 2"],
  "counter_argument": "1-2 sentences arguing the OPPOSITE position — what's the strongest case against this thesis?",
  "tax_notes":        "Lithuanian tax angle: capital gains 15%, dividend tax 15%, €500 annual exemption. For Irish UCITS note favorable treatment; for US-domiciled note 30% withholding."
}

Rules:
- Every number you cite must come from the supplied data — do not invent metrics.
- "key_risks" should be 2-4 items; "invalidation_triggers" should be 1-3 falsifiable conditions.
- For ETFs, the fundamental_case discusses domicile/distribution/expense ratio instead of P/E.
- counter_argument is required — it must NOT just restate the risks. Argue the opposite reading.
- No markdown, no commentary outside the JSON object.
"""


@dataclass
class BaseThesis:
    """Timeframe-agnostic, ticker-level thesis from the LLM."""
    ticker: str
    technical_case: str
    fundamental_case: str
    sentiment_case: str
    macro_context: str
    key_risks: list[str]
    invalidation_triggers: list[str]
    counter_argument: str
    tax_notes: str
    data_quality: str         # "full" | "degraded" | "missing"
    raw_response: str = ""    # for debugging / data-repo audit
    duration_ms: int | None = None
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "technical_case": self.technical_case,
            "fundamental_case": self.fundamental_case,
            "sentiment_case": self.sentiment_case,
            "macro_context": self.macro_context,
            "key_risks": self.key_risks,
            "invalidation_triggers": self.invalidation_triggers,
            "counter_argument": self.counter_argument,
            "tax_notes": self.tax_notes,
            "data_quality": self.data_quality,
            "duration_ms": self.duration_ms,
            "model": self.model,
        }


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------
def generate_base_thesis(
    ctx: AnalysisContext,
    module_results: dict[str, ModuleResult],
    *,
    client: LLMClient | None = None,
) -> BaseThesis:
    """Call the configured LLM once for this ticker. Returns a structured
    thesis or a degraded fallback if the LLM is unreachable / returns junk.
    """
    client = client or get_llm_client()
    user_prompt = _build_user_prompt(ctx, module_results)
    quality_overall = _aggregate_data_quality(module_results)

    try:
        resp = client.generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            # Reasoning models (DeepSeek V4 Pro, gpt-5/o3, claude with extended
            # thinking) charge reasoning tokens against max_tokens. A full
            # structured rationale is ~500-800 output tokens; deep reasoning
            # adds 1500-3000 more. 6144 leaves comfortable headroom so the
            # JSON doesn't get truncated mid-string.
            max_tokens=6144,
            seed=42,  # deterministic-ish for the same inputs
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM unavailable for %s: %s — falling back to template", ctx.ticker, exc)
        return _template_fallback(ctx, module_results, quality=quality_overall, reason=str(exc))

    parsed = resp.parsed
    if not parsed:
        client_name = type(client).__name__
        log.warning(
            "%s returned non-JSON for %s (likely truncated mid-output — bump max_tokens if persistent); falling back",
            client_name, ctx.ticker,
        )
        return _template_fallback(
            ctx, module_results,
            quality=quality_overall,
            reason=f"{client_name} non-JSON response",
        )

    return BaseThesis(
        ticker=ctx.ticker,
        technical_case=str(parsed.get("technical_case", "") or ""),
        fundamental_case=str(parsed.get("fundamental_case", "") or ""),
        sentiment_case=str(parsed.get("sentiment_case", "") or ""),
        macro_context=str(parsed.get("macro_context", "") or ""),
        key_risks=_as_str_list(parsed.get("key_risks")),
        invalidation_triggers=_as_str_list(parsed.get("invalidation_triggers")),
        counter_argument=str(parsed.get("counter_argument", "") or ""),
        tax_notes=str(parsed.get("tax_notes", "") or ""),
        data_quality=quality_overall,
        raw_response=resp.text[:4000],
        duration_ms=resp.duration_ms,
        model=client.model,
    )


# ---------------------------------------------------------------------------
# Per-cell adaptation — no LLM
# ---------------------------------------------------------------------------
def adapt_thesis_for_cell(base: BaseThesis, candidate: Candidate) -> dict:
    """Build the full per-cell rationale from a base thesis + candidate."""
    direction_label = {
        "buy": "Buy", "avoid": "Avoid (no clear signal)", "sell_short": "Sell-short",
    }.get(candidate.direction, candidate.direction)

    headline = f"{candidate.ticker} — {direction_label} for {candidate.timeframe} ({candidate.risk_profile})"

    why_tf = _why_this_timeframe(candidate)

    confidence_drivers = []
    for c in candidate.contributors[:5]:
        confidence_drivers.append({
            "factor": c["module"],
            "delta": round(c["weighted_contrib"], 3),
            "reason": _short_reason_for_module(c),
        })

    # Full scoring breakdown — exposes the per-module math behind the call.
    scoring_breakdown = {
        "cell_score": candidate.cell_score,
        "cell_confidence": candidate.cell_confidence,
        "direction": candidate.direction,
        "direction_threshold": DIRECTION_THRESHOLD,
        "min_confidence": MIN_CONFIDENCE,
        "filter_passed": candidate.filter_passed,
        "filter_reason": candidate.filter_reason,
        "contributors": [
            {
                "module": c["module"],
                "score": c["score"],
                "confidence": c["confidence"],
                "cell_weight": c["cell_w"],
                "horizon_weight": c["horizon_w"],
                "contribution": c["weighted_contrib"],
            }
            for c in candidate.contributors
        ],
        "raw_module_scores": candidate.raw_module_scores,
    }

    return {
        "headline": headline,
        "technical_case": base.technical_case,
        "fundamental_case": base.fundamental_case,
        "sentiment_case": base.sentiment_case,
        "macro_context": base.macro_context,
        "why_this_timeframe": why_tf,
        "key_risks": base.key_risks,
        "invalidation_triggers": base.invalidation_triggers,
        "counter_argument": base.counter_argument,
        "confidence_drivers": confidence_drivers,
        "scoring_breakdown": scoring_breakdown,
        "tax_notes": base.tax_notes,
        "data_quality": base.data_quality,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_user_prompt(ctx: AnalysisContext, results: dict[str, ModuleResult]) -> str:
    """Assemble the structured analysis snapshot the LLM sees."""
    summary = {
        "ticker": ctx.ticker,
        "asset_type": ctx.asset_type,
        "snapshot_date": ctx.snapshot_date.isoformat(),
        "metadata": ctx.metadata or {},
        "modules": {name: r.to_dict() for name, r in results.items()},
        "errors": ctx.errors,
    }
    return (
        "Produce the JSON analysis for this ticker. The data below is the "
        "structured output of 13 analysis modules — base your reasoning ONLY "
        "on these numbers, do not invent metrics.\n\n"
        + json.dumps(summary, default=str, indent=2)[:14000]
    )


def _aggregate_data_quality(results: dict[str, ModuleResult]) -> str:
    """Roll up per-module quality into a single label."""
    n = len(results)
    if n == 0:
        return "missing"
    full = sum(1 for r in results.values() if r.data_quality == "full")
    missing = sum(1 for r in results.values() if r.data_quality == "missing")
    if missing > n // 2:
        return "degraded"
    if full >= n * 0.6:
        return "full"
    return "degraded"


def _template_fallback(
    ctx: AnalysisContext,
    results: dict[str, ModuleResult],
    *,
    quality: str,
    reason: str,
) -> BaseThesis:
    """No-LLM fallback. Surfaces the strongest module notes verbatim so the
    suggestion still has SOME rationale even if Ollama is down.
    """
    notes_by_module = {name: r.notes for name, r in results.items() if r.notes}

    def _notes_for(*module_names: str) -> str:
        text = []
        for n in module_names:
            for note in notes_by_module.get(n, [])[:2]:
                text.append(note)
        return " ".join(text) or "No notes from this analysis branch."

    return BaseThesis(
        ticker=ctx.ticker,
        technical_case=_notes_for("technical", "momentum", "mean_reversion", "volatility_regime"),
        fundamental_case=_notes_for("fundamental_equity", "etf_fundamental", "quality"),
        sentiment_case=_notes_for("news_sentiment", "social_sentiment", "insider_institutional"),
        macro_context=_notes_for("macro"),
        key_risks=["LLM unavailable — risks not articulated."],
        invalidation_triggers=["LLM unavailable — invalidation triggers not articulated."],
        counter_argument="LLM unavailable — no counter-argument generated.",
        tax_notes="See ETF-fundamental notes for LT tax annotations." if ctx.asset_type == "etf"
                  else "LT capital gains 15%, €500 annual exemption applies.",
        data_quality="degraded",
        raw_response=f"FALLBACK: {reason}",
        model="(fallback)",
    )


def _why_this_timeframe(c: Candidate) -> str:
    """Template the per-timeframe rationale from the dominant contributor."""
    if not c.contributors:
        return "No dominant signal at this horizon."
    top = c.contributors[0]
    return (
        f"At the {c.timeframe} horizon, the {top['module']} signal is the "
        f"dominant contributor (weight {top['horizon_w']:.2f} × score "
        f"{top['score']:+.2f}). Cell score {c.cell_score:+.2f} with "
        f"confidence {c.cell_confidence:.0%}."
    )


def _short_reason_for_module(c: dict) -> str:
    contrib = c.get("weighted_contrib", 0.0)
    if contrib > 0.05:
        return f"strong positive contribution at this horizon ({contrib:+.2f})"
    if contrib < -0.05:
        return f"strong negative contribution at this horizon ({contrib:+.2f})"
    return f"minor contribution ({contrib:+.2f})"


def _as_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v if x][:5]
    if isinstance(v, str):
        return [v]
    return []
