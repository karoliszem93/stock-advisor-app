"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.db import init_db
from app.routes import health, run, suggestions, validations, watchlist
from app.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting stock-advisor backend v%s", __version__)
    init_db()
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
