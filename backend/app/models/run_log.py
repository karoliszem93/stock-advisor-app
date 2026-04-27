"""RunLog — one row per pipeline invocation (daily run, validation sweep, manual trigger)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RunLog(Base, TimestampMixin):
    __tablename__ = "run_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # "daily_pipeline" | "validation_sweep" | "manual"
    run_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # "running" | "ok" | "partial" | "failed"
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Code git SHA pinned at run time — the future agent reads this to know
    # exactly which version of the pipeline produced the day's data.
    code_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ollama_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Per-source error log: { provider_name: error_message }
    errors: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Free-form summary numbers: { suggestions_generated: N, validated: N, ... }
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
