"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.db import init_db
from app.routes import health, providers, run, runs, suggestions, validations, watchlist
from app.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
# Silence successful-HTTP request logs from httpx — they drown out the
# pipeline's own progress lines. Errors still surface from each provider.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("yfinance").setLevel(logging.ERROR)
log = logging.getLogger("app.main")


def _clear_stale_runs() -> None:
    """Mark any RunLog rows still in 'running' state at startup as failed.

    These are leftovers from a previous backend that was killed mid-pipeline
    before its except/finally block could update the status.
    """
    from datetime import datetime, timezone
    from app.db import SessionLocal
    from app.models import RunLog
    from sqlalchemy import select

    db = SessionLocal()
    try:
        stale = db.scalars(select(RunLog).where(RunLog.status == "running")).all()
        for r in stale:
            r.status = "failed"
            r.finished_at = datetime.now(timezone.utc)
            r.errors = {**(r.errors or {}), "startup_cleanup": "marked failed (process killed)"}
        if stale:
            db.commit()
            log.info("Marked %d stale 'running' run(s) as failed at startup", len(stale))
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting stock-advisor backend v%s", __version__)
    init_db()
    _clear_stale_runs()
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()
        log.info("Shutdown complete.")


app = FastAPI(
    title="stock-advisor",
    version=__version__,
    description="Localhost stock investment advisor backend.",
    lifespan=lifespan,
)

# Frontend dev server runs on :5173 — allow it to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(health.router, tags=["health"])
app.include_router(suggestions.router, prefix="/api/suggestions", tags=["suggestions"])
app.include_router(validations.router, prefix="/api/validations", tags=["validations"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(run.router, prefix="/api/run", tags=["run"])
app.include_router(providers.router, prefix="/api/providers", tags=["providers"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
