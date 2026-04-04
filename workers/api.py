"""Minimal FastAPI app for human review (NEEDS_REVIEW) and manual corrections."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from sqlalchemy import select

from workers.db.crud import get_job, record_human_correction
from workers.db.models import InvoiceJob, JobStatus
from workers.db.session import SessionLocal, init_db
from workers.utils.metrics import METRICS


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Invoice pipeline review", version="1.0.0", lifespan=_lifespan)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class CorrectionBody(BaseModel):
    vendor: str = Field(..., min_length=2, max_length=100)
    invoice_date: str = Field(..., description="YYYY-MM-DD or DD/MM/YYYY")
    total_amount: float = Field(..., gt=0)
    note: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    return METRICS.snapshot()


def _job_to_review_dict(j: InvoiceJob) -> dict[str, Any]:
    return {
        "job_id": j.job_id,
        "image_path": j.image_path,
        "status": j.status,
        "last_error": j.last_error,
        "ocr_snapshot": j.ocr_snapshot,
        "llm_last_raw": (j.llm_last_raw or "")[:2000],
        "extraction_payload": j.extraction_payload,
        "retry_history": j.retry_history,
    }


def _fetch_needs_review(db: Session, limit: int) -> list[dict[str, Any]]:
    """Jobs that failed after the single allowed retry — same rows as ``human_review_queue.json``."""
    stmt = (
        select(InvoiceJob)
        .where(InvoiceJob.status == JobStatus.NEEDS_REVIEW.value)
        .order_by(InvoiceJob.updated_at.desc())
        .limit(limit)
    )
    rows = list(db.scalars(stmt).all())
    return [_job_to_review_dict(j) for j in rows]


@app.get("/jobs/needs-review")
def list_needs_review_endpoint(db: Session = Depends(get_db), limit: int = 50) -> list[dict[str, Any]]:
    return _fetch_needs_review(db, limit)


@app.get("/jobs/dlq")
def list_dlq_alias(db: Session = Depends(get_db), limit: int = 50) -> list[dict[str, Any]]:
    """Backward-compatible alias: returns NEEDS_REVIEW jobs (legacy DLQ is no longer written)."""
    return _fetch_needs_review(db, limit)


@app.post("/jobs/{job_id}/correct")
def correct(job_id: str, body: CorrectionBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    record_human_correction(
        db,
        job_id,
        vendor=body.vendor,
        invoice_date=body.invoice_date,
        total_amount=body.total_amount,
        note=body.note,
    )
    return {"ok": True, "job_id": job_id}


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
