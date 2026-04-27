"""SQLAlchemy engine + session factory for the local SQLite working DB.

The data repo on GitHub is the durable source of truth; this DB is just a
fast working store for the live UI and current-day pipeline state.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

_engine = create_engine(
    f"sqlite:///{_settings.db_path}",
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


def get_engine():
    return _engine


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a session and closes it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they don't exist. Called on startup."""
    # Import models here to register them on the metadata before create_all.
    from app.models import base as _base  # noqa: F401
    from app.models import run_log as _run_log  # noqa: F401
    from app.models import suggestion as _suggestion  # noqa: F401
    from app.models import watchlist as _watchlist  # noqa: F401

    _base.Base.metadata.create_all(bind=_engine)
