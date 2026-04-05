"""Wait until ingested jobs reach a terminal DB state (SUCCESS, NEEDS_REVIEW, or legacy DLQ)."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from receipt_pipeline.workers.db.models import InvoiceJob, JobStatus
from receipt_pipeline.workers.db.session import SessionLocal
from receipt_pipeline.workers.utils.pipeline_log import pl_info
from config.logger_setup import get_logger

logger = get_logger()

_TERMINAL = frozenset(
    {
        JobStatus.SUCCESS.value,
        JobStatus.NEEDS_REVIEW.value,
        JobStatus.DLQ.value,
    }
)


def _scalars_all(session, stmt, *, attempts: int = 12) -> list:
    """Retry briefly on SQLite 'database is locked' under concurrent workers."""
    delay = 0.05
    last: OperationalError | None = None
    for i in range(attempts):
        try:
            return list(session.scalars(stmt).all())
        except OperationalError as e:
            last = e
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            if i == attempts - 1:
                break
            time.sleep(delay)
            delay = min(delay * 1.5, 1.0)
    assert last is not None
    raise last


def wait_for_terminal_jobs(
    job_ids: list[str],
    *,
    timeout_sec: float = 3600.0,
    poll_sec: float = 1.0,
) -> tuple[list[str], list[str]]:
    """
    Poll the DB until every job_id is terminal (SUCCESS / NEEDS_REVIEW / DLQ) or timeout.
    Returns (success_ids, needs_review_ids).
    """
    if not job_ids:
        return [], []

    job_ids = list(dict.fromkeys(job_ids))
    deadline = time.monotonic() + timeout_sec
    pending = set(job_ids)
    pl_info(
        "orchestrator",
        "wait_terminal_start",
        jobs=len(job_ids),
        timeout_sec=timeout_sec,
        poll_sec=poll_sec,
        meaning="blocks_until_SUCCESS_or_NEEDS_REVIEW_or_legacy_DLQ",
    )
    last_stall_log = time.monotonic()

    while time.monotonic() < deadline and pending:
        session = SessionLocal()
        try:
            stmt = select(InvoiceJob).where(InvoiceJob.job_id.in_(pending))
            rows = _scalars_all(session, stmt)
            by_id = {r.job_id: r for r in rows}
            for jid in list(pending):
                row = by_id.get(jid)
                if row and row.status in _TERMINAL:
                    pending.discard(jid)
        finally:
            session.close()

        if pending:
            now = time.monotonic()
            if now - last_stall_log >= 30.0:
                pl_info(
                    "orchestrator",
                    "still_processing",
                    pending_count=len(pending),
                    sample_job_ids=list(pending)[:8],
                    hint="OCR_rules_LLM_and_validation_still_in_flight",
                )
                last_stall_log = now
            time.sleep(poll_sec)

    if pending:
        raise TimeoutError(
            f"Timed out waiting for jobs to finish. Still pending: {sorted(pending)[:20]}"
        )

    session = SessionLocal()
    try:
        stmt = select(InvoiceJob).where(InvoiceJob.job_id.in_(job_ids))
        rows = _scalars_all(session, stmt)
        ok = [r.job_id for r in rows if r.status == JobStatus.SUCCESS.value]
        needs_review = [
            r.job_id
            for r in rows
            if r.status in (JobStatus.NEEDS_REVIEW.value, JobStatus.DLQ.value)
        ]
        pl_info(
            "orchestrator",
            "wait_terminal_done",
            success=len(ok),
            needs_review=len(needs_review),
            job_ids_checked=len(job_ids),
        )
        return ok, needs_review
    finally:
        session.close()
