"""Strict validation → SUCCESS, one LLM retry, or NEEDS_REVIEW + human_review_queue.json."""

from __future__ import annotations  # modern typing

import json
import threading

# Queues
from receipt_pipeline.workers.config import Q_LLM, Q_VALIDATE

# DB operations
from receipt_pipeline.db.crud import append_retry_history, get_job, increment_retry, update_job
from receipt_pipeline.db.models import ExtractionSource, JobStatus
from receipt_pipeline.db.session import SessionLocal

from receipt_pipeline.workers.utils.metrics import METRICS
from receipt_pipeline.workers.utils.pipeline_log import pl_error, pl_info, pl_warning


from receipt_pipeline.redis_queue import get_redis

# Retry system
from receipt_pipeline.workers.retry.retry_ops import schedule_retry
from receipt_pipeline.workers.retry.retry_strategy import next_llm_strategy


from config.logger_setup import get_logger


from receipt_pipeline.pipeline.validation.validation_layer import validate_extracted_invoice

from receipt_pipeline.workers.human_review_store import finalize_needs_human_review

logger = get_logger()


def validate_once(job_id: str) -> None:
    """
    Validate extracted invoice data:
    - If valid → SUCCESS
    - If invalid → retry via LLM
    - If max retries → send to human review
    """

    r = get_redis()
    session = SessionLocal()

    try:
       
        job = get_job(session, job_id)

        # If no job or no extracted data → skip
        if not job or not job.extraction_payload:
            pl_warning("validate", "missing_payload", job_id=job_id)
            return

        # If already processed → skip
        if job.status == JobStatus.SUCCESS.value:
            pl_info("validate", "skip_already_success", job_id=job_id)
            return

        ep = job.extraction_payload  # extracted data

        pl_info(
            "validate",
            "check_schema_and_rules",
            job_id=job_id,
            source=ep.get("source"),
            vendor=ep.get("vendor"),
            date=ep.get("date"),
            total=ep.get("total"),
        )

        # Runs strict validation (format + business rules)
        vr = validate_extracted_invoice(
            ep.get("file") or job.image_path,
            ep.get("vendor"),
            ep.get("date"),
            ep.get("total"),
        )

        if vr.ok and vr.normalized:
            norm = vr.normalized  # cleaned/normalized data

            # Save final result in DB
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

        # ---------------- CASE 2: INVALID ----------------
        errs = ",".join(vr.errors)  # collect validation errors
        prev = job.attempt_strategy  # previous LLM strategy

        pl_warning(
            "validate",
            "FAIL",
            job_id=job_id,
            errors=vr.errors,
            previous_strategy=prev,
        )

        # Save retry history
        append_retry_history(
            session,
            job_id,
            {"stage": "validate", "errors": vr.errors, "payload_keys": list(ep.keys())},
        )

      
        row = increment_retry(session, job_id)


        if row and row.retry_count >= row.max_retries:
            METRICS.inc("dlq_entries")

            # Move to human review queue
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

        # ---------------- CASE : RETRY WITH LLM ----------------
        # Choose better strategy (e.g., stricter prompt)
        nxt = next_llm_strategy("validation", prev)

        # Schedule retry (delayed push to Q_LLM)
        delay = schedule_retry(
            r,
            job_id=job_id,
            retry_count=row.retry_count - 1 if row else 0,
            failure_class="validation",
            target_queue=Q_LLM,
            payload={"job_id": job_id, "strategy": nxt},
            job_failures_so_far=row.retry_count if row else None,
        )

        # Update job state
        update_job(
            session,
            job_id,
            status=JobStatus.RETRY_SCHEDULED.value,
            last_error=f"validation:{errs}",
            failure_class="validation",
        )

        # Log retry decision
        pl_info(
            "validate",
            "schedule_retry_LLM",
            job_id=job_id,
            next_strategy=nxt,
            retry_after_sec=round(delay, 1),
            decision="retry_LLM_with_stricter_prompt",
        )

    # ---------------- ERROR HANDLING ----------------
    except Exception as e:
        session.rollback()
        logger.exception("validate_once job_id=%s: %s", job_id, e)
        pl_error("validate", "stage_exception", job_id=job_id, error=str(e))
        try:
            append_retry_history(session, job_id, {"stage": "validate", "error": str(e)})
            row = increment_retry(session, job_id)
            if row and row.retry_count >= row.max_retries:
                METRICS.inc("dlq_entries")
                finalize_needs_human_review(
                    session,
                    job_id,
                    stage="validation_exception",
                    reason=f"validation_exception_after_retry:{e}",
                )
                pl_warning(
                    "validate",
                    "exception_max_retries_NEEDS_HUMAN_REVIEW",
                    job_id=job_id,
                    decision="NEEDS_REVIEW",
                    error=str(e),
                )
            else:
                delay = schedule_retry(
                    r,
                    job_id=job_id,
                    retry_count=(row.retry_count - 1) if row else 0,
                    failure_class="validation_exception",
                    target_queue=Q_VALIDATE,
                    payload={"job_id": job_id},
                    job_failures_so_far=row.retry_count if row else None,
                )
                update_job(
                    session,
                    job_id,
                    status=JobStatus.RETRY_SCHEDULED.value,
                    last_error=f"validation_exception:{e}",
                    failure_class="validation_exception",
                )
                pl_info(
                    "validate",
                    "exception_schedule_retry_validate",
                    job_id=job_id,
                    retry_after_sec=round(delay, 1),
                    decision="retry_validation_stage",
                )
        except Exception as recovery_error:
            session.rollback()
            logger.exception("validate_once recovery failed job_id=%s: %s", job_id, recovery_error)
            pl_error(
                "validate",
                "exception_recovery_failed",
                job_id=job_id,
                error=str(recovery_error),
            )

    finally:
        session.close()


# ---------------- WORKER LOOP ----------------
def validate_worker_loop(stop_event: threading.Event) -> None:
    """
    Continuously:
    - Listen to validation queue
    - Process jobs using validate_once()
    """

    r = get_redis()

    # Worker startup log
    pl_info("validate", "worker_ready", queue=Q_VALIDATE, waits_for="rule_or_LLM_extractions")
    logger.info("validate worker started")

    while not stop_event.is_set():
        try:
            # Blocking pop from queue
            item = r.brpop(Q_VALIDATE, timeout=2)

            if not item:
                continue

            _, raw = item
            msg = json.loads(raw)

            jid = msg["job_id"]

            # Log job pickup
            pl_info("validate", "dequeued_job", job_id=jid)

            # Process job
            validate_once(jid)

        except Exception as e:
            # Prevent worker crash
            logger.exception("validate_worker_loop: %s", e)