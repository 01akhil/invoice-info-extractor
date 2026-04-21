"""OCR stage: CPU-bound worker loop (run N processes)."""

from __future__ import annotations 
import json

from receipt_pipeline.workers.config import Q_OCR, Q_POST_OCR

# DB operations for job lifecycle + retries
from receipt_pipeline.db.crud import append_retry_history, get_job, increment_retry, update_job
from receipt_pipeline.db.models import JobStatus
from receipt_pipeline.db.session import SessionLocal

# Metrics collection (for observability)
from receipt_pipeline.workers.utils.metrics import METRICS

# Redis queue connection
from receipt_pipeline.redis_queue import get_redis

from receipt_pipeline.workers.utils.pipeline_log import pl_error, pl_info, pl_warning

# Retry scheduling logic (exponential backoff .)
from receipt_pipeline.workers.retry.retry_ops import schedule_retry

# Logger setup
from config.logger_setup import get_logger

# OCR engine + custom error
from receipt_pipeline.ocr.ocr import OCRReader, CorruptedImageError

logger = get_logger()

def _ocr_once(job_id: str) -> None:
    """
    Process a single OCR job:
    - Fetch job from DB
    - Run OCR
    - Save results
    - Push to next stage (POST_OCR)
    - Handle retries / corrupted files
    """
    from receipt_pipeline.pipeline.stages import ocr_results_to_serializable

    r = get_redis()                 # Redis connection
    session = SessionLocal()        # DB session

    try:
        # Fetch job from DB
        job = get_job(session, job_id)
        if not job:
            # Job not found → skip
            pl_warning("ocr", "job_not_found_in_db", job_id=job_id)
            return

        # Skip if job already finished or dead-lettered
        if job.status in (
            JobStatus.SUCCESS.value,
            JobStatus.DLQ.value,
            JobStatus.NEEDS_REVIEW.value,
        ):
            pl_info("ocr", "skip_already_terminal", job_id=job_id, status=job.status)
            return

        # Prevent duplicate processing (idempotency guard)
        if job.status == JobStatus.PROCESSING.value:
            pl_warning("ocr", "skip_already_processing", job_id=job_id)
            return

        # Log input file being processed
        pl_info(
            "ocr",
            "input_file_processing",
            job_id=job_id,
            input_file=job.image_path,
            decision="run_OCRReader.read",
        )

        # Mark job as PROCESSING
        update_job(session, job_id, status=JobStatus.PROCESSING.value, failure_class="ocr")

        # ---------------- OCR EXECUTION ----------------
        ocr = OCRReader()
        _image, ocr_results = ocr.read(job.image_path)  # CPU-heavy OCR call

        # Convert OCR results into JSON-serializable format
        snap = ocr_results_to_serializable(ocr_results)
        n_regions = len(snap) if isinstance(snap, list) else 0

        # Save OCR results in DB
        update_job(
            session,
            job_id,
            status=JobStatus.OCR_DONE.value,
            ocr_snapshot=snap,
            last_error=None,
        )

        # Push job to next stage queue (POST_OCR)
        r.lpush(Q_POST_OCR, json.dumps({"job_id": job_id}))

        # Log success
        pl_info(
            "ocr",
            "tesseract_done",
            job_id=job_id,
            text_regions=n_regions,
            next_queue=Q_POST_OCR,
            decision="enqueue_rules_and_routing",
        )

    # ---------------- CORRUPTED FILE HANDLING ----------------
    except CorruptedImageError as e:
        session.rollback()  # rollback DB transaction
        METRICS.inc("ocr_corrupted")  # increment metric

        logger.warning("Corrupted image for job_id=%s: %s", job_id, str(e))

        # Log pipeline event
        pl_warning(
            "ocr",
            "corrupted_file_skipped",
            job_id=job_id,
            error=str(e),
            decision="mark_NEEDS_REVIEW_no_retry",
        )

        # Store failure history
        append_retry_history(session, job_id, {"stage": "ocr", "error": str(e)})

        # Mark job as NEEDS_REVIEW (no retry for corrupted files)
        update_job(
            session,
            job_id,
            status=JobStatus.NEEDS_REVIEW.value,
            last_error=str(e),
            failure_class="ocr_corrupted",
        )
        return

    # ---------------- RETRYABLE FAILURES ----------------
    except Exception as e:
        session.rollback()
        METRICS.inc("ocr_fail")

        logger.exception("ocr failed job_id=%s", job_id)

        # Structured logging
        pl_error(
            "ocr",
            "stage_failed",
            job_id=job_id,
            error=str(e),
            decision="retry_or_NEEDS_REVIEW",
        )

        # Store retry history
        append_retry_history(session, job_id, {"stage": "ocr", "error": str(e)})

        # Increment retry counter
        row = increment_retry(session, job_id)

        # -------- MAX RETRIES EXCEEDED --------
        if row and row.retry_count >= row.max_retries:
            from receipt_pipeline.workers.human_review_store import finalize_needs_human_review

            METRICS.inc("dlq_entries")

            # Move job to human review (DLQ equivalent)
            finalize_needs_human_review(
                session,
                job_id,
                stage="ocr",
                reason=f"ocr_failed_after_retry:{e}",
            )

            pl_warning(
                "ocr",
                "failed_max_retries_NEEDS_HUMAN_REVIEW",
                job_id=job_id,
                retries=row.retry_count,
                error=str(e),
                decision="NEEDS_REVIEW",
            )

        # -------- SCHEDULE RETRY --------
        else:
            delay = schedule_retry(
                r,
                job_id=job_id,
                retry_count=(row.retry_count - 1) if row else 0,
                failure_class="ocr",
                target_queue=Q_OCR,   # retry same stage
                payload={"job_id": job_id},
                job_failures_so_far=row.retry_count if row else None,
            )

            # Update job state
            update_job(
                session,
                job_id,
                status=JobStatus.RETRY_SCHEDULED.value,
                last_error=str(e),
            )

            pl_info(
                "ocr",
                "failed_schedule_retry",
                job_id=job_id,
                retry_after_sec=round(delay, 1),
                target_queue=Q_OCR,
                decision="retry_same_stage_OCR",
            )

    finally:
        session.close()  # always close DB session


def ocr_worker_loop(stop_event, worker_id: int) -> None:
    """
    Infinite worker loop:
    - Pull jobs from Redis queue (blocking)
    - Process using _ocr_once
    - Runs until stop_event is triggered
    """
    r = get_redis()

    # Worker startup log
    pl_info(
        "ocr",
        "worker_ready",
        worker_id=worker_id,
        queue=Q_OCR,
        waits_for="jobs_from_ingest",
    )

    logger.info("OCR worker %s started", worker_id)

    # Continuous polling loop
    while not stop_event.is_set():
        try:
            # Blocking pop (waits for job)
            item = r.brpop(Q_OCR, timeout=2)
            if not item:
                continue  # no job → keep waiting

            _, raw = item
            msg = json.loads(raw)
            jid = msg["job_id"]

            # Log dequeue
            pl_info("ocr", "dequeued_job", worker_id=worker_id, job_id=jid)
            logger.info("OCR worker %s picked job %s", worker_id, jid)

            # Process job
            _ocr_once(jid)

        except Exception as e:
            # Catch-all to prevent worker crash
            logger.exception("ocr_worker_loop: %s", e)