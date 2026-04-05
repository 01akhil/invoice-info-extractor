from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from receipt_pipeline.workers.db.models import ExtractionSource, HumanCorrection, InvoiceJob, JobStatus


def get_job(session: Session, job_id: str) -> InvoiceJob | None:
    return session.get(InvoiceJob, job_id)


def create_job(
    session: Session,
    job_id: str,
    image_path: str,
    max_retries: int = 2,
) -> InvoiceJob:
    row = InvoiceJob(
        job_id=job_id,
        image_path=image_path,
        status=JobStatus.PENDING.value,
        max_retries=max_retries,
        retry_history=[],
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_job(session: Session, job_id: str, **fields: Any) -> InvoiceJob | None:
    row = get_job(session, job_id)
    if not row:
        return None
    for k, v in fields.items():
        if hasattr(row, k):
            setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(row)
    return row


def increment_retry(session: Session, job_id: str) -> InvoiceJob | None:
    row = get_job(session, job_id)
    if not row:
        return None
    row.retry_count = (row.retry_count or 0) + 1
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(row)
    return row


def append_retry_history(session: Session, job_id: str, entry: dict) -> None:
    row = get_job(session, job_id)
    if not row:
        return
    hist = list(row.retry_history or [])
    hist.append(entry)
    row.retry_history = hist
    row.updated_at = datetime.now(timezone.utc)
    session.commit()


def record_human_correction(
    session: Session,
    job_id: str,
    vendor: str | None,
    invoice_date: str | None,
    total_amount: float | None,
    note: str | None = None,
) -> HumanCorrection:
    hc = HumanCorrection(
        job_id=job_id,
        vendor=vendor,
        invoice_date=invoice_date,
        total_amount=total_amount,
        reviewer_note=note,
    )
    session.add(hc)
    job = get_job(session, job_id)
    if job:
        job.vendor = vendor
        job.invoice_date = invoice_date
        job.total_amount = total_amount
        job.status = JobStatus.SUCCESS.value
        job.source = ExtractionSource.HUMAN.value
        job.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(hc)
    return hc


def list_jobs_by_status(session: Session, status: str, limit: int = 100) -> list[InvoiceJob]:
    stmt = select(InvoiceJob).where(InvoiceJob.status == status).order_by(InvoiceJob.updated_at.desc()).limit(limit)
    return list(session.scalars(stmt).all())
