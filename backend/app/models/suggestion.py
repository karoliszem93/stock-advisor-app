"""Suggestion + SuggestionValidation models.

A Suggestion is an immutable record of a recommendation produced on a given
date for a (ticker, timeframe, risk) cell. Once written it is never updated;
the validation outcome is stored in a separate SuggestionValidation row.

The full data snapshot used to produce the suggestion lives in the data repo
(at suggestions/<date>/<risk>/<timeframe>.json plus analysis/<date>/<ticker>.json).
This SQLite row is the working-DB pointer — we keep enough fields for fast UI
queries; the source of truth is the JSON file path.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Suggestion(Base, TimestampMixin):
    __tablename__ = "suggestion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ---- identity ----
    suggestion_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)  # equity | etf
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    # one of: 1w 2w 1m 3m 6m 1y 3y
    risk_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    # one of: conservative balanced growth aggressive

    # ---- recommendation ----
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    # one of: buy avoid sell_short
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0..1
    confidence_calibrated: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ---- prices (in EUR — see returns_breakdown for native + FX) ----
    entry_price_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # ---- relative position sizing (no portfolio tracking — % of capital) ----
    suggested_risk_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ---- pointers to durable record ----
    data_repo_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    suggestion_json_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    analysis_json_path: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # ---- thesis & rationale (short snapshot — full content lives in JSON file) ----
    headline: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rationale: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # rationale shape: see SCHEMAS.md in stock-advisor-data
    # {
    #   "technical_case": "...",
    #   "fundamental_case": "...",
    #   "sentiment_case": "...",
    #   "macro_context": "...",
    #   "why_this_timeframe": "...",
    #   "key_risks": ["..."],
    #   "invalidation_triggers": ["..."],
    #   "confidence_drivers": [{"factor": "...", "delta": 0.05}],
    #   "tax_notes": "...",
    #   "data_quality": "full" | "degraded"
    # }

    validations: Mapped[list["SuggestionValidation"]] = relationship(
        back_populates="suggestion",
        cascade="all, delete-orphan",
    )


class SuggestionValidation(Base, TimestampMixin):
    """Outcome record written by the validation sweep when target_date hits."""

    __tablename__ = "suggestion_validation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    suggestion_id: Mapped[int] = mapped_column(
        ForeignKey("suggestion.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Outcome
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    # correct | incorrect | partial
    outcome_score: Mapped[float] = mapped_column(Float, nullable=False)  # -1 .. +1

    # Returns breakdown (all in EUR), computed at target_date
    actual_price_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_dividend_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_fx_effect_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_total_return_pct_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    after_tax_return_pct_eur: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Excursion analytics
    max_favorable_excursion_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_adverse_excursion_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_hit: Mapped[bool | None] = mapped_column(nullable=True)
    stop_hit: Mapped[bool | None] = mapped_column(nullable=True)

    notes: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    suggestion: Mapped["Suggestion"] = relationship(back_populates="validations")
