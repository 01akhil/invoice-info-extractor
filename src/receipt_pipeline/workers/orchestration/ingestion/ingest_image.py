"""Create a single idempotent job row and enqueue OCR stage."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from receipt_pipeline.workers.config import PIPELINE_MAX_FAILURES_BEFORE_REVIEW, Q_OCR
from receipt_pipeline.db.crud import create_job, get_job
from receipt_pipeline.db.session import SessionLocal
from receipt_pipeline.workers.utils.pipeline_log import pl_info


def ingest_image(r, image_path: str, job_id: str | None = None) -> str:
    """
    Create DB row (PENDING) and push to OCR queue.
    Idempotent: no duplicate DB rows; re-enqueues if still PENDING after a crash.
    """
    path = str(Path(image_path).resolve())
    jid = job_id or str(uuid.uuid4())

    session = SessionLocal()
    #implementing idempotency
    try:
        existing = get_job(session, jid)

        if existing:
            if existing.status == "PENDING":
                r.lpush(Q_OCR, json.dumps({"job_id": jid}))
                pl_info("ingest", "re_enqueue_pending_job", job_id=jid)
            else:
                pl_info(
                    "ingest",
                    "skip_duplicate_job",
                    job_id=jid,
                    status=existing.status,
                )
            return jid

        create_job(session, jid, path, max_retries=PIPELINE_MAX_FAILURES_BEFORE_REVIEW)
        r.lpush(Q_OCR, json.dumps({"job_id": jid}))
        pl_info(
            "ingest",
            "job_created",
            job_id=jid,
            image=path,
            next_queue=Q_OCR,
            decision="enqueue_OCR",
        )
        return jid
    finally:
        session.close()
