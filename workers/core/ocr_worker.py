"""OCR stage: CPU-bound worker loop (run N processes)."""

from __future__ import annotations
import json

from workers.config import Q_OCR, Q_POST_OCR
from workers.db.crud import append_retry_history, get_job, increment_retry, update_job
from workers.db.models import JobStatus
from workers.db.session import SessionLocal
from workers.utils.metrics import METRICS
from workers.redis.redis_client import get_redis
from workers.utils.pipeline_log import pl_error, pl_info, pl_warning
from workers.retry.retry_ops import schedule_retry
from config.logger_setup import get_logger

from ocr.ocr import OCRReader, CorruptedImageError

logger = get_logger()


def _ocr_once(job_id: str) -> None:
    """Process a single OCR job safely with retries and corrupted file handling."""
    from pipeline.stages import ocr_results_to_serializable

    r = get_redis()
    session = SessionLocal()

    try:
        job = get_job(session, job_id)
        if not job:
            pl_warning("ocr", "job_not_found_in_db", job_id=job_id)
            return

        # Skip terminal states
        if job.status in (
            JobStatus.SUCCESS.value,
            JobStatus.DLQ.value,
            JobStatus.NEEDS_REVIEW.value,
        ):
            pl_info("ocr", "skip_already_terminal", job_id=job_id, status=job.status)
            return

        # Prevent duplicate parallel processing
        if job.status == JobStatus.PROCESSING.value:
            pl_warning("ocr", "skip_already_processing", job_id=job_id)
            return

        pl_info(
            "ocr",
            "input_file_processing",
            job_id=job_id,
            input_file=job.image_path,
            decision="run_OCRReader.read",
        )

        update_job(session, job_id, status=JobStatus.PROCESSING.value, failure_class="ocr")

        # Run OCR
        ocr = OCRReader()
        _image, ocr_results = ocr.read(job.image_path)

        snap = ocr_results_to_serializable(ocr_results)
        n_regions = len(snap) if isinstance(snap, list) else 0

        update_job(
            session,
            job_id,
            status=JobStatus.OCR_DONE.value,
            ocr_snapshot=snap,
            last_error=None,
        )

        r.lpush(Q_POST_OCR, json.dumps({"job_id": job_id}))
        METRICS.inc("ocr_success")

        pl_info(
            "ocr",
            "tesseract_done",
            job_id=job_id,
            text_regions=n_regions,
            next_queue=Q_POST_OCR,
            decision="enqueue_rules_and_routing",
        )

    # Corrupted image → mark as NEEDS_REVIEW, do NOT retry
    except CorruptedImageError as e:
        session.rollback()
        METRICS.inc("ocr_corrupted")

        logger.warning("Corrupted image for job_id=%s: %s", job_id, str(e))

        pl_warning(
            "ocr",
            "corrupted_file_skipped",
            job_id=job_id,
            error=str(e),
            decision="mark_NEEDS_REVIEW_no_retry",
        )

        append_retry_history(session, job_id, {"stage": "ocr", "error": str(e)})

        update_job(
            session,
            job_id,
            status=JobStatus.NEEDS_REVIEW.value,
            last_error=str(e),
            failure_class="ocr_corrupted",
        )
        return

    # Retryable failures
    except Exception as e:
        session.rollback()
        METRICS.inc("ocr_fail")

        logger.exception("ocr failed job_id=%s", job_id)

        pl_error(
            "ocr",
            "stage_failed",
            job_id=job_id,
            error=str(e),
            decision="retry_or_NEEDS_REVIEW",
        )

        append_retry_history(session, job_id, {"stage": "ocr", "error": str(e)})
        row = increment_retry(session, job_id)

        if row and row.retry_count >= row.max_retries:
            from workers.human_review_store import finalize_needs_human_review

            METRICS.inc("dlq_entries")

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
        else:
            delay = schedule_retry(
                r,
                job_id=job_id,
                retry_count=(row.retry_count - 1) if row else 0,
                failure_class="ocr",
                target_queue=Q_OCR,
                payload={"job_id": job_id},
                job_failures_so_far=row.retry_count if row else None,
            )

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
        session.close()


def ocr_worker_loop(stop_event, worker_id: int) -> None:
    """Continuously pick jobs from OCR queue and process them."""
    r = get_redis()

    pl_info(
        "ocr",
        "worker_ready",
        worker_id=worker_id,
        queue=Q_OCR,
        waits_for="jobs_from_ingest",
    )

    logger.info("OCR worker %s started", worker_id)

    while not stop_event.is_set():
        try:
            item = r.brpop(Q_OCR, timeout=2)
            if not item:
                continue

            _, raw = item
            msg = json.loads(raw)
            jid = msg["job_id"]

            pl_info("ocr", "dequeued_job", worker_id=worker_id, job_id=jid)
            logger.info("OCR worker %s picked job %s", worker_id, jid)

            _ocr_once(jid)

        except Exception as e:
            logger.exception("ocr_worker_loop: %s", e)