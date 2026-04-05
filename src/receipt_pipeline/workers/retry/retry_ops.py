"""Exponential backoff scheduling onto Redis ZSET; worker moves due jobs back to target queues."""

from __future__ import annotations

import json
import random
import time
from typing import Any

import redis

from receipt_pipeline.workers.config import RETRY_BASE_SEC, RETRY_CAP_SEC, RETRY_ZSET
from receipt_pipeline.workers.utils.metrics import METRICS
from receipt_pipeline.workers.utils.pipeline_log import pl_info


def schedule_retry(
    r: redis.Redis,
    *,
    job_id: str,
    retry_count: int,
    failure_class: str,
    target_queue: str,
    payload: dict[str, Any],
    job_failures_so_far: int | None = None,
) -> float:
    """Schedule a retry; returns scheduled delay seconds. ``retry_count`` is the backoff exponent index."""
    delay = min(RETRY_CAP_SEC, RETRY_BASE_SEC * (2**retry_count)) + random.uniform(0, 1.5)
    score = time.time() + delay
    envelope = {
        "job_id": job_id,
        "queue": target_queue,
        "payload": payload,
        "failure_class": failure_class,
    }
    r.zadd(RETRY_ZSET, {json.dumps(envelope): score})
    METRICS.inc("retry_scheduled")
    fields: dict[str, object] = {
        "job_id": job_id,
        "failure_class": failure_class,
        "delay_sec": round(delay, 2),
        "target_queue": target_queue,
        "next_payload_strategy": payload.get("strategy"),
        "backoff_exponent_index": retry_count,
    }
    if job_failures_so_far is not None:
        fields["job_failures_so_far"] = job_failures_so_far
        fields["retry_attempt_number"] = job_failures_so_far + 1
    pl_info(
        "retry",
        "scheduled_backoff",
        **fields,
    )
    return delay


def retry_scheduler_loop(r: redis.Redis, stop_event, logger) -> None:
    """Move due retries from ZSET to their target lists."""
    from receipt_pipeline.workers.config import RETRY_POLL_SEC

    while not stop_event.is_set():
        try:
            now = time.time()
            # Fetch due entries (small batches)
            due = r.zrangebyscore(RETRY_ZSET, "-inf", now, start=0, num=50)
            for raw in due:
                if r.zrem(RETRY_ZSET, raw) == 0:
                    continue
                try:
                    env = json.loads(raw)
                    q = env["queue"]
                    payload = env["payload"]
                    jid = payload.get("job_id", "?")
                    pl_info(
                        "retry",
                        "due_requeue",
                        job_id=jid,
                        target_queue=q,
                        failure_class=env.get("failure_class"),
                        note="retry_attempt_executing",
                    )
                    r.lpush(q, json.dumps(payload))
                except Exception as e:
                    logger.exception("Bad retry envelope: %s err=%s", raw, e)
        except Exception as e:
            logger.exception("retry_scheduler_loop: %s", e)
        stop_event.wait(RETRY_POLL_SEC)
