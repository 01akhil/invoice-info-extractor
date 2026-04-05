"""Rule extraction + confidence routing → LLM queue or validate queue."""

from __future__ import annotations

import json
import threading

from receipt_pipeline.workers.config import Q_LLM, Q_POST_OCR, Q_VALIDATE
from receipt_pipeline.workers.db.crud import get_job, update_job
from receipt_pipeline.workers.db.models import JobStatus
from receipt_pipeline.workers.db.session import SessionLocal
from receipt_pipeline.workers.utils.metrics import METRICS
from receipt_pipeline.workers.utils.pipeline_log import pl_info, pl_warning
from receipt_pipeline.workers.redis.redis_client import get_redis
from config.logger_setup import get_logger
from receipt_pipeline.pipeline.stages import (
    build_extraction_payload,
    run_rule_extraction,
    serializable_to_ocr_results,
    should_route_to_llm,
)

logger = get_logger()


def post_ocr_once(job_id: str, strategy: str = "default") -> None:
    r = get_redis()
    session = SessionLocal()
    try:
        job = get_job(session, job_id)
        if not job or not job.ocr_snapshot:
            pl_warning("rules", "missing_job_or_ocr_snapshot", job_id=job_id)
            return
        pl_info(
            "rules",
            "start_rule_extract_and_route",
            job_id=job_id,
            image=job.image_path,
            strategy=strategy,
        )
        ocr_results = serializable_to_ocr_results(job.ocr_snapshot)
        rule = run_rule_extraction(job.image_path, ocr_results)
        vc, tc, dc = rule["vendor_conf"], rule["total_conf"], rule["date_conf"]
        route_llm = should_route_to_llm(vc, tc, dc)
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
        if route_llm:
            METRICS.inc("llm_fallback_routed")
            update_job(
                session,
                job_id,
                status=JobStatus.LLM_PENDING.value,
                attempt_strategy=strategy,
            )
            r.lpush(Q_LLM, json.dumps({"job_id": job_id, "strategy": strategy}))
            pl_info(
                "rules",
                "decision_route_LLM",
                job_id=job_id,
                reason="low_confidence_on_one_or_more_fields",
                next_queue=Q_LLM,
                llm_strategy=strategy,
            )
            return
        payload = build_extraction_payload(rule, source="OCR_RULE", llm_used=False)
        update_job(
            session,
            job_id,
            status=JobStatus.VALIDATING.value,
            extraction_payload=payload,
            attempt_strategy=strategy,
        )
        r.lpush(Q_VALIDATE, json.dumps({"job_id": job_id}))
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
    except Exception as e:
        session.rollback()
        logger.exception("post_ocr_once job_id=%s: %s", job_id, e)
    finally:
        session.close()


def post_ocr_worker_loop(stop_event: threading.Event) -> None:
    r = get_redis()
    pl_info("rules", "worker_ready", queue=Q_POST_OCR, waits_for="OCR_done_jobs")
    logger.info("post_ocr worker started")
    while not stop_event.is_set():
        try:
            item = r.brpop(Q_POST_OCR, timeout=2)
            if not item:
                continue
            _, raw = item
            msg = json.loads(raw)
            jid = msg["job_id"]
            pl_info("rules", "dequeued_job", job_id=jid, strategy=msg.get("strategy", "default"))
            post_ocr_once(jid, strategy=msg.get("strategy", "default"))
        except Exception as e:
            logger.exception("post_ocr_worker_loop: %s", e)
