"""Rule extraction + confidence routing → LLM queue or validate queue."""

from __future__ import annotations 
import json
import threading

# Queue names for routing
from receipt_pipeline.workers.config import Q_LLM, Q_POST_OCR, Q_VALIDATE

# DB operations
from receipt_pipeline.db.crud import get_job, update_job
from receipt_pipeline.db.models import JobStatus
from receipt_pipeline.db.session import SessionLocal

# Metrics utilities
from receipt_pipeline.workers.utils.metrics import METRICS
from receipt_pipeline.workers.utils.pipeline_log import pl_info, pl_warning

# Redis queue connection
from receipt_pipeline.redis_queue import get_redis

# Logger
from config.logger_setup import get_logger

# Core pipeline logic functions
from receipt_pipeline.pipeline.stages import (
    build_extraction_payload,      # Build structured output
    ocr_snapshot_has_regions,      # Distinguish missing snapshot vs empty OCR []
    run_rule_extraction,           # Rule-based extraction (vendor, total, date)
    serializable_to_ocr_results,   # Convert stored JSON → OCR objects
    should_route_to_llm,           # Decision function (LLM vs rules)
)
from receipt_pipeline.workers.human_review_store import finalize_needs_human_review

logger = get_logger()


def post_ocr_once(job_id: str, strategy: str = "default") -> None:
    """
    Process a single job after OCR:
    - Convert OCR snapshot
    - Run rule-based extraction
    - Check confidence scores
    - Route to LLM OR validation queue
    """

    r = get_redis()             # Redis connection
    session = SessionLocal()    # DB session

    try:
        # ---------------- FETCH JOB ----------------
        job = get_job(session, job_id)

        if not job:
            pl_warning("rules", "missing_job", job_id=job_id)
            return

        # OCR not persisted yet (should be rare if dequeued from post-OCR)
        if job.ocr_snapshot is None:
            pl_warning("rules", "missing_ocr_snapshot", job_id=job_id)
            return

        # Tesseract returned zero regions: [] is falsy but is valid "OCR done" — terminal review
        if not ocr_snapshot_has_regions(job.ocr_snapshot):
            METRICS.inc("ocr_no_text_regions")
            finalize_needs_human_review(
                session,
                job_id,
                stage="ocr",
                reason="ocr_no_text_regions",
            )
            pl_info(
                "rules",
                "decision_empty_ocr_NEEDS_REVIEW",
                job_id=job_id,
                image=job.image_path,
                reason="tesseract_zero_text_regions",
                next_status="NEEDS_REVIEW",
            )
            return

        # Log start of rule extraction
        pl_info(
            "rules",
            "start_rule_extract_and_route",
            job_id=job_id,
            image=job.image_path,
            strategy=strategy,
        )

        # ---------------- PREPARE OCR DATA ----------------
        # Convert stored JSON snapshot back into OCR result objects
        ocr_results = serializable_to_ocr_results(job.ocr_snapshot)

        # ---------------- RULE-BASED EXTRACTION ----------------
        # Extract fields like vendor, total, date + confidence scores
        rule = run_rule_extraction(job.image_path, ocr_results)

        # Extract confidence scores
        vc, tc, dc = rule["vendor_conf"], rule["total_conf"], rule["date_conf"]

        # ---------------- DECISION: ROUTE TO LLM OR NOT ----------------
        route_llm = should_route_to_llm(vc, tc, dc)

        # Log confidence values and decision
        pl_info(
            "rules",
            "confidences",
            job_id=job_id,
            vendor_conf=round(vc, 4),
            total_conf=round(tc, 4),
            date_conf=round(dc, 4),
            route_to_llm_rule="vendor<0.5 OR total<0.05 OR date<0.1",
            result_route_llm=route_llm,
        )

        # ---------------- LOW CONFIDENCE → SEND TO LLM ----------------
        if route_llm:
            # Increment metric (LLM fallback usage)
            METRICS.inc("llm_fallback_routed")

            # Update job status → waiting for LLM
            update_job(
                session,
                job_id,
                status=JobStatus.LLM_PENDING.value,
                attempt_strategy=strategy,
            )

            # Push job to LLM queue
            r.lpush(Q_LLM, json.dumps({"job_id": job_id, "strategy": strategy}))

            # Log routing decision
            pl_info(
                "rules",
                "decision_route_LLM",
                job_id=job_id,
                reason="low_confidence_on_one_or_more_fields",
                next_queue=Q_LLM,
                llm_strategy=strategy,
            )
            return  # Stop further processing

        # ---------------- HIGH CONFIDENCE → SKIP LLM ----------------
        # Build structured payload from rule extraction
        payload = build_extraction_payload(rule, source="OCR_RULE", llm_used=False)

        # Update job → move to validation stage
        update_job(
            session,
            job_id,
            status=JobStatus.VALIDATING.value,
            extraction_payload=payload,
            attempt_strategy=strategy,
        )

        # Push to validation queue
        r.lpush(Q_VALIDATE, json.dumps({"job_id": job_id}))

        # Log fast-path decision (no LLM used)
        pl_info(
            "rules",
            "decision_fast_path_validate",
            job_id=job_id,
            reason="confidences_high_enough_skip_LLM",
            source="OCR_RULE",
            next_queue=Q_VALIDATE,
            preview_vendor=payload.get("vendor"),
            preview_total=payload.get("total"),
            preview_date=payload.get("date"),
        )

    # ---------------- ERROR HANDLING ----------------
    except Exception as e:
        # Rollback DB transaction on failure
        session.rollback()

        # Log error (does NOT crash worker)
        logger.exception("post_ocr_once job_id=%s: %s", job_id, e)

    finally:
        # Always close DB session
        session.close()


def post_ocr_worker_loop(stop_event: threading.Event) -> None:
    """
    Worker loop:
    - Continuously listens to Q_POST_OCR queue
    - Picks jobs and processes them via post_ocr_once()
    """

    r = get_redis()

    # Log worker startup
    pl_info("rules", "worker_ready", queue=Q_POST_OCR, waits_for="OCR_done_jobs")
    logger.info("post_ocr worker started")

    # Infinite loop (until stop_event is triggered)
    while not stop_event.is_set():
        try:
            # Blocking pop from Redis queue (waits up to 2 sec)
            item = r.brpop(Q_POST_OCR, timeout=2)

            # If no job → continue loop
            if not item:
                continue

            # Extract message from Redis
            _, raw = item
            msg = json.loads(raw)

            # Get job ID
            jid = msg["job_id"]

            # Log job pickup
            pl_info(
                "rules",
                "dequeued_job",
                job_id=jid,
                strategy=msg.get("strategy", "default"),
            )

            # Process job
            post_ocr_once(jid, strategy=msg.get("strategy", "default"))

        except Exception as e:
            # Prevent worker crash on unexpected errors
            logger.exception("post_ocr_worker_loop: %s", e)