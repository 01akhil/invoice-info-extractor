"""Strict validation → SUCCESS, one LLM retry, or NEEDS_REVIEW + human_review_queue.json."""

from __future__ import annotations

import json
import threading

from workers.config import Q_LLM, Q_VALIDATE
from workers.db.crud import append_retry_history, get_job, increment_retry, update_job
from workers.db.models import ExtractionSource, JobStatus
from workers.db.session import SessionLocal
from workers.utils.metrics import METRICS
from workers.utils.pipeline_log import pl_error, pl_info, pl_warning
from workers.redis.redis_client import get_redis
from workers.retry.retry_ops import schedule_retry
from workers.retry.retry_strategy import next_llm_strategy
from config.logger_setup import get_logger
from pipeline.validation.validation_layer import validate_extracted_invoice
from workers.human_review_store import finalize_needs_human_review

logger = get_logger()


def validate_once(job_id: str) -> None:
    r = get_redis()
    session = SessionLocal()
    try:
        job = get_job(session, job_id)
        if not job or not job.extraction_payload:
            pl_warning("validate", "missing_payload", job_id=job_id)
            return
        if job.status == JobStatus.SUCCESS.value:
            pl_info("validate", "skip_already_success", job_id=job_id)
            return
        ep = job.extraction_payload
        pl_info(
            "validate",
            "check_schema_and_rules",
            job_id=job_id,
            source=ep.get("source"),
            vendor=ep.get("vendor"),
            date=ep.get("date"),
            total=ep.get("total"),
        )
        vr = validate_extracted_invoice(
            ep.get("file") or job.image_path,
            ep.get("vendor"),
            ep.get("date"),
            ep.get("total"),
        )
        if vr.ok and vr.normalized:
            norm = vr.normalized
            update_job(
                session,
                job_id,
                status=JobStatus.SUCCESS.value,
                vendor=str(norm.get("vendor")),
                invoice_date=str(norm.get("date")),
                total_amount=float(norm.get("total")),
                confidence=float(ep.get("confidence") or 0.0),
                source=ep.get("source") or ExtractionSource.UNKNOWN.value,
                last_error=None,
            )
            METRICS.inc("success_total")
            pl_info(
                "validate",
                "PASS",
                job_id=job_id,
                event_extracted_values=True,
                vendor=norm.get("vendor"),
                date=norm.get("date"),
                total=norm.get("total"),
                decision="STORE_SUCCESS_in_DB",
            )
            return

        # METRICS.inc("validation_fail")
        errs = ",".join(vr.errors)
        prev = job.attempt_strategy
        pl_warning(
            "validate",
            "FAIL",
            job_id=job_id,
            errors=vr.errors,
            previous_strategy=prev,
        )
        append_retry_history(
            session,
            job_id,
            {"stage": "validate", "errors": vr.errors, "payload_keys": list(ep.keys())},
        )
        row = increment_retry(session, job_id)
        if row and row.retry_count >= row.max_retries:
            METRICS.inc("dlq_entries")
            finalize_needs_human_review(
                session,
                job_id,
                stage="validation",
                reason=f"validation_failed_after_retry:{errs}",
            )
            pl_warning(
                "validate",
                "max_retries_NEEDS_HUMAN_REVIEW",
                job_id=job_id,
                decision="NEEDS_REVIEW",
                file="results/human_review_queue.json",
                errors=vr.errors,
            )
            return

        nxt = next_llm_strategy("validation", prev)
        delay = schedule_retry(
            r,
            job_id=job_id,
            retry_count=row.retry_count - 1 if row else 0,
            failure_class="validation",
            target_queue=Q_LLM,
            payload={"job_id": job_id, "strategy": nxt},
            job_failures_so_far=row.retry_count if row else None,
        )
        update_job(
            session,
            job_id,
            status=JobStatus.RETRY_SCHEDULED.value,
            last_error=f"validation:{errs}",
            failure_class="validation",
        )
        pl_info(
            "validate",
            "schedule_retry_LLM",
            job_id=job_id,
            next_strategy=nxt,
            retry_after_sec=round(delay, 1),
            decision="retry_LLM_with_stricter_prompt",
        )
    except Exception as e:
        session.rollback()
        logger.exception("validate_once job_id=%s: %s", job_id, e)
        pl_error("validate", "stage_exception", job_id=job_id, error=str(e))
    finally:
        session.close()


def validate_worker_loop(stop_event: threading.Event) -> None:
    r = get_redis()
    pl_info("validate", "worker_ready", queue=Q_VALIDATE, waits_for="rule_or_LLM_extractions")
    logger.info("validate worker started")
    while not stop_event.is_set():
        try:
            item = r.brpop(Q_VALIDATE, timeout=2)
            if not item:
                continue
            _, raw = item
            msg = json.loads(raw)
            jid = msg["job_id"]
            pl_info("validate", "dequeued_job", job_id=jid)
            validate_once(jid)
        except Exception as e:
            logger.exception("validate_worker_loop: %s", e)
