"""Ingestion: create idempotent jobs and enqueue OCR stage."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import redis

from workers.config import PIPELINE_MAX_FAILURES_BEFORE_REVIEW, Q_OCR
from workers.db.crud import create_job, get_job
from workers.db.session import SessionLocal
from workers.utils.pipeline_log import pl_info, pl_warning


def ingest_image(r: redis.Redis, image_path: str, job_id: str | None = None) -> str:
    """
    Create DB row (PENDING) and push to OCR queue.
    Idempotent: if job_id already exists, returns existing id without duplicate enqueue.
    """
    path = str(Path(image_path).resolve())
    jid = job_id or str(uuid.uuid4())
    session = SessionLocal()
    try:
        existing = get_job(session, jid)
        if existing:
            pl_info("ingest", "skip_duplicate_job", job_id=jid, reason="already_in_db")
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


def ingest_folder(r: redis.Redis, folder: Path) -> list[str]:
    exts = {".jpg", ".jpeg", ".png"}
    if not folder.is_dir():
        pl_warning("ingest", "folder_missing_or_not_a_directory", path=str(folder))
        return []
    ids: list[str] = []
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() in exts:
            ids.append(ingest_image(r, str(p)))
    pl_info("ingest", "folder_scan_done", folder=str(folder), jobs_enqueued=len(ids))
    return ids
