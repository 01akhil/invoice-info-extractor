"""Persist jobs that need human review to a JSON file (single retry exhausted)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from config.settings import RESULTS_DIR
from receipt_pipeline.workers.db.crud import get_job, update_job
from receipt_pipeline.workers.db.models import InvoiceJob, JobStatus
from config.logger_setup import get_logger

logger = get_logger()

HUMAN_REVIEW_QUEUE_PATH = RESULTS_DIR / "human_review_queue.json"
_MAX_JSON_FIELD = 12_000


def _truncate_for_file(obj: Any, max_chars: int = _MAX_JSON_FIELD) -> Any:
    if obj is None:
        return None
    try:
        s = json.dumps(obj, default=str)
    except TypeError:
        return str(obj)[:500]
    if len(s) <= max_chars:
        return obj
    return {"_truncated": True, "preview": s[: max_chars // 2] + "..."}


def build_review_record(job: InvoiceJob, *, stage: str, reason: str) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "image_path": job.image_path,
        "status": JobStatus.NEEDS_REVIEW.value,
        "stage_failed": stage,
        "reason": reason,
        "last_error": job.last_error,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "failure_class": job.failure_class,
        "attempt_strategy": job.attempt_strategy,
        "ocr_snapshot": _truncate_for_file(job.ocr_snapshot),
        "extraction_payload": _truncate_for_file(job.extraction_payload),
        "llm_last_raw": (job.llm_last_raw or "")[:4000] if job.llm_last_raw else None,
        "retry_history": job.retry_history,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def persist_human_review_record(record: dict[str, Any]) -> Path:
    """Merge into `human_review_queue.json` by `job_id` (latest wins)."""
    HUMAN_REVIEW_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if HUMAN_REVIEW_QUEUE_PATH.exists():
        try:
            raw = HUMAN_REVIEW_QUEUE_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, list):
                existing = data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read %s: %s — starting fresh list", HUMAN_REVIEW_QUEUE_PATH, e)

    jid = record.get("job_id")
    existing = [x for x in existing if isinstance(x, dict) and x.get("job_id") != jid]
    existing.append(record)
    tmp = HUMAN_REVIEW_QUEUE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
    tmp.replace(HUMAN_REVIEW_QUEUE_PATH)
    logger.info("Human review queue updated: %s (entries=%s)", HUMAN_REVIEW_QUEUE_PATH, len(existing))
    return HUMAN_REVIEW_QUEUE_PATH


def finalize_needs_human_review(
    session: Session,
    job_id: str,
    *,
    stage: str,
    reason: str,
) -> None:
    """
    Set status NEEDS_REVIEW and append/merge a row in ``results/human_review_queue.json``.
    Call when retry budget is exhausted (only one retry allowed).
    """
    job = get_job(session, job_id)
    if not job:
        return
    update_job(
        session,
        job_id,
        status=JobStatus.NEEDS_REVIEW.value,
        last_error=reason,
        failure_class=stage,
    )
    session.refresh(job)
    record = build_review_record(job, stage=stage, reason=reason)
    persist_human_review_record(record)
