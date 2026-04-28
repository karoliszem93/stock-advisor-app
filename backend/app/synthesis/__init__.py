"""Synthesis layer — turns analysis results into ranked suggestions.

Pipeline order:
  1. weights.py     Default per-cell (risk × timeframe) module weights.
  2. scorer.py      Combines module scores + applies risk filters + ranks.
  3. ollama_client  Local-LLM wrapper with JSON-mode prompting.
  4. thesis.py      Builds the LLM prompt and parses the structured reply.
  5. orchestrator   Top-level: snapshot → analyze → score → thesis → persist.
"""

from app.synthesis.weights import (
    RISK_PROFILES,
    TIMEFRAMES,
    cell_weights,
    timeframe_to_target_date,
)

__all__ = [
    "RISK_PROFILES",
    "TIMEFRAMES",
    "cell_weights",
    "timeframe_to_target_date",
]
