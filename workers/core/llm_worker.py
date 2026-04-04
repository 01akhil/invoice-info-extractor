"""LLM extraction: batched Gemini calls (2–3 invoices per prompt) with single-job fallback."""

from __future__ import annotations

import json
import threading

from workers.config import (
    LLM_BATCH_FIRST_WAIT_SEC,
    LLM_BATCH_INTER_WAIT_SEC,
    LLM_BATCH_MAX,
    Q_LLM,
    Q_VALIDATE,
)
from workers.db.crud import append_retry_history, get_job, increment_retry, update_job
from workers.db.models import JobStatus
from workers.db.session import SessionLocal
from workers.utils.metrics import METRICS
from workers.utils.pipeline_log import pl_info, pl_warning
from workers.redis.redis_client import get_redis
from workers.retry.retry_ops import schedule_retry
from workers.retry.retry_strategy import next_llm_strategy
from config.logger_setup import get_logger
from pipeline.batch_llm import merge_batch_strategies, run_batch_llm_extraction
from pipeline.fallback import run_llm_extraction
from pipeline.stages import extraction_payload_from_llm_parsed, serializable_to_ocr_results

logger = get_logger()


def collect_llm_batch(r, queue: str) -> list[dict]:
    """Block for first job, then short-wait for more until batch max."""
    batch: list[dict] = []
    t_first = max(1, int(LLM_BATCH_FIRST_WAIT_SEC))
    item = r.brpop(queue, timeout=t_first)
    if not item:
        return []
    batch.append(json.loads(item[1]))
    while len(batch) < LLM_BATCH_MAX:
        t_inter = max(1, int(LLM_BATCH_INTER_WAIT_SEC))
        item2 = r.brpop(queue, timeout=t_inter)
        if not item2:
            break
        batch.append(json.loads(item2[1]))
    return batch


def _execute_single_llm(job_id: str, strategy: str) -> None:
    """One invoice, one LLM API call (fallback path)."""
    r = get_redis()
    session = SessionLocal()
    try:
        job = get_job(session, job_id)
        if not job or not job.ocr_snapshot:
            pl_warning("llm", "missing_job_or_ocr_snapshot", job_id=job_id)
            return

        pl_info(
            "llm",
            "call_gemini_single",
            job_id=job_id,
            image=job.image_path,
            prompt_strategy=strategy,
            decision="run_llm_extraction",
        )
        ocr_results = serializable_to_ocr_results(job.ocr_snapshot)
        parsed, raw = run_llm_extraction(ocr_results, strategy=strategy)
        METRICS.inc("llm_invocations")
        METRICS.inc("llm_single_calls")
        raw_store = (raw or "")[:8000]
        update_job(session, job_id, llm_last_raw=raw_store, attempt_strategy=strategy)

        if not parsed:
            _handle_single_parse_failure(r, session, job_id, strategy, raw)
            return

        payload = extraction_payload_from_llm_parsed(job.image_path, parsed, llm_used=True)
        update_job(
            session,
            job_id,
            extraction_payload=payload,
            status=JobStatus.VALIDATING.value,
        )
        r.lpush(Q_VALIDATE, json.dumps({"job_id": job_id}))
        pl_info(
            "llm",
            "parse_ok",
            job_id=job_id,
            strategy=strategy,
            vendor=payload.get("vendor"),
            total=payload.get("total"),
            date=payload.get("date"),
            next_queue=Q_VALIDATE,
            decision="enqueue_validation",
        )
    except Exception as e:
        session.rollback()
        logger.exception("llm_once failed job_id=%s", job_id)
        pl_warning("llm", "exception_during_llm_stage", job_id=job_id, strategy=strategy, error=str(e))
        _handle_single_exception(r, session, job_id, strategy, e)
    finally:
        session.close()


def _handle_single_parse_failure(r, session, job_id: str, strategy: str, raw: str) -> None:
    pl_warning(
        "llm",
        "parse_empty_or_invalid_JSON",
        job_id=job_id,
        strategy=strategy,
        raw_len=len(raw or ""),
    )
    append_retry_history(session, job_id, {"stage": "llm", "error": "empty_parse", "strategy": strategy})
    row = increment_retry(session, job_id)
    if row and row.retry_count >= row.max_retries:
        from workers.human_review_store import finalize_needs_human_review

        METRICS.inc("dlq_entries")
        finalize_needs_human_review(
            session,
            job_id,
            stage="llm",
            reason="llm_parse_failed_after_retry",
        )
        pl_warning(
            "llm",
            "failed_max_retries_NEEDS_HUMAN_REVIEW",
            job_id=job_id,
            decision="NEEDS_REVIEW",
            file="results/human_review_queue.json",
            reason="llm_parse",
        )
    else:
        nxt = next_llm_strategy("llm", strategy)
        delay = schedule_retry(
            r,
            job_id=job_id,
            retry_count=row.retry_count - 1 if row else 0,
            failure_class="llm",
            target_queue=Q_LLM,
            payload={"job_id": job_id, "strategy": nxt},
            job_failures_so_far=row.retry_count if row else None,
        )
        update_job(session, job_id, status=JobStatus.RETRY_SCHEDULED.value)
        pl_info(
            "llm",
            "schedule_retry_new_strategy",
            job_id=job_id,
            next_strategy=nxt,
            retry_after_sec=round(delay, 1),
            decision="retry_LLM_with_improved_prompt",
        )


def _handle_single_exception(r, session, job_id: str, strategy: str, e: BaseException) -> None:
    try:
        append_retry_history(session, job_id, {"stage": "llm", "error": str(e), "strategy": strategy})
        row = increment_retry(session, job_id)
        if row and row.retry_count >= row.max_retries:
            from workers.human_review_store import finalize_needs_human_review

            METRICS.inc("dlq_entries")
            finalize_needs_human_review(
                session,
                job_id,
                stage="llm",
                reason=f"llm_exception_after_retry:{e}",
            )
            pl_warning(
                "llm",
                "failed_max_retries_NEEDS_HUMAN_REVIEW",
                job_id=job_id,
                decision="NEEDS_REVIEW",
                file="results/human_review_queue.json",
                reason="exception",
            )
        else:
            nxt = next_llm_strategy("llm", strategy)
            delay = schedule_retry(
                r,
                job_id=job_id,
                retry_count=row.retry_count - 1 if row else 0,
                failure_class="llm",
                target_queue=Q_LLM,
                payload={"job_id": job_id, "strategy": nxt},
                job_failures_so_far=row.retry_count if row else None,
            )
            update_job(session, job_id, status=JobStatus.RETRY_SCHEDULED.value, last_error=str(e))
            pl_info(
                "llm",
                "schedule_retry_after_exception",
                job_id=job_id,
                next_strategy=nxt,
                retry_after_sec=round(delay, 1),
            )
    except Exception as inner:
        logger.exception("llm_once recovery failed: %s", inner)


def _llm_batch_once(messages: list[dict]) -> None:
    """Process up to LLM_BATCH_MAX jobs in one Gemini call."""
    r = get_redis()
    session = SessionLocal()
    try:
        assert session is not None
        loaded: list[tuple[object, str]] = []
        for m in messages:
            jid = m["job_id"]
            st = m.get("strategy", "default")
            job = get_job(session, jid)
            if not job or not job.ocr_snapshot:
                pl_warning("llm", "batch_skip_missing_job", job_id=jid)
                continue
            loaded.append((job, st))

        if not loaded:
            session.close()
            return

        strategies = [st for _, st in loaded]
        merged = merge_batch_strategies(strategies)
        items = [
            (j.job_id, j.image_path, serializable_to_ocr_results(j.ocr_snapshot))
            for j, _ in loaded
        ]

        pl_info(
            "llm",
            "call_gemini_batch",
            batch_size=len(items),
            job_ids=[j.job_id for j, _ in loaded],
            merged_strategy=merged,
            decision="one_API_call_multi_invoice",
        )

        parsed_map, raw = run_batch_llm_extraction(items, strategy=merged)
        METRICS.inc("llm_invocations")
        METRICS.inc("llm_batch_calls")
        raw_store = (raw or "")[:12000]
        for j, _ in loaded:
            update_job(session, j.job_id, llm_last_raw=raw_store, attempt_strategy=merged)

        if not parsed_map:
            pl_warning(
                "llm",
                "batch_parse_failed_fallback_singles",
                batch_size=len(loaded),
            )
            session.close()
            session = None
            for j, st in loaded:
                _execute_single_llm(j.job_id, st)
            return

        missing: list[tuple[str, str]] = []
        for j, st in loaded:
            jid = j.job_id
            one = parsed_map.get(jid)
            if one is None:
                for k, v in parsed_map.items():
                    if str(k).strip() == str(jid).strip():
                        one = v
                        break
            if not one:
                pl_warning("llm", "batch_missing_job_in_response", job_id=jid, fallback="single")
                missing.append((jid, st))
                continue

            payload = extraction_payload_from_llm_parsed(j.image_path, one, llm_used=True)
            update_job(
                session,
                jid,
                extraction_payload=payload,
                status=JobStatus.VALIDATING.value,
            )
            r.lpush(Q_VALIDATE, json.dumps({"job_id": jid}))
            pl_info(
                "llm",
                "batch_item_ok",
                job_id=jid,
                vendor=payload.get("vendor"),
                total=payload.get("total"),
                date=payload.get("date"),
                next_queue=Q_VALIDATE,
            )

        session.close()
        session = None

        for jid, st in missing:
            _execute_single_llm(jid, st)

    except Exception as e:
        if session is not None:
            session.rollback()
        logger.exception("llm_batch_once: %s", e)
        pl_warning("llm", "batch_exception_fallback_singles", error=str(e))
        if session is not None:
            session.close()
            session = None
        for m in messages:
            _execute_single_llm(m["job_id"], m.get("strategy", "default"))
    finally:
        if session is not None:
            session.close()


def llm_worker_loop(stop_event: threading.Event, pool_size: int) -> None:
    """Single-threaded loop: collect batch → one Gemini call → validate queue per job."""
    r = get_redis()
    del pool_size  # batch worker uses one thread; kept for API compatibility
    pl_info(
        "llm",
        "worker_ready",
        queue=Q_LLM,
        batch_max=LLM_BATCH_MAX,
        first_wait_sec=LLM_BATCH_FIRST_WAIT_SEC,
        inter_wait_sec=LLM_BATCH_INTER_WAIT_SEC,
    )
    logger.info(
        "LLM batch worker: max=%s per API call, first_wait=%ss, inter_wait=%ss",
        LLM_BATCH_MAX,
        LLM_BATCH_FIRST_WAIT_SEC,
        LLM_BATCH_INTER_WAIT_SEC,
    )
    while not stop_event.is_set():
        try:
            batch = collect_llm_batch(r, Q_LLM)
            if not batch:
                continue
            pl_info("llm", "dequeued_batch", count=len(batch), job_ids=[b.get("job_id") for b in batch])
            _llm_batch_once(batch)
        except Exception as e:
            logger.exception("llm_worker_loop: %s", e)
