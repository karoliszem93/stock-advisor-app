"""Watchlist — tickers the user explicitly wants analyzed every run."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WatchlistItem(Base, TimestampMixin):
    __tablename__ = "watchlist"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
