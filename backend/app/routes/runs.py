"""Run history endpoint — surfaces RunLog rows so the UI can show
the latest pipeline run status and any degraded-data warnings.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import RunLog

router = APIRouter()


@router.get("/")
def list_runs(
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=200),
    run_type: str | None = None,
) -> list[dict]:
    stmt = select(RunLog).order_by(RunLog.started_at.desc()).limit(limit)
    if run_type:
        stmt = stmt.where(RunLog.run_type == run_type)
    rows = db.scalars(stmt).all()
    return [_row(r) for r in rows]


@router.get("/latest")
def latest_run(db: Session = Depends(get_db), run_type: str | None = "daily_pipeline") -> dict | None:
    stmt = select(RunLog).order_by(RunLog.started_at.desc()).limit(1)
    if run_type:
        stmt = stmt.where(RunLog.run_type == run_type)
    row = db.scalars(stmt).first()
    return _row(row) if row else None


def _row(r: RunLog) -> dict:
    return {
        "id": r.id,
        "run_type": r.run_type,
        "status": r.status,
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "code_sha": r.code_sha,
        "ollama_model": r.ollama_model,
        "summary": r.summary,
        "errors": r.errors,
    }
