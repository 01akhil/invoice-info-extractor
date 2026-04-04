"""
Pipeline tuning (queues, Redis, workers). Values come from :mod:`config.settings`.

Import from here for stable worker package paths, or use ``config.settings`` directly.
"""

from __future__ import annotations

from config.settings import (
    CB_FAIL_THRESHOLD,
    CB_OPEN_SEC,
    DLQ_LIST,
    LLM_BATCH_FIRST_WAIT_SEC,
    LLM_BATCH_INTER_WAIT_SEC,
    LLM_BATCH_MAX,
    LLM_THREAD_POOL,
    OCR_PROCESSES,
    PIPELINE_MAX_FAILURES_BEFORE_REVIEW,
    PIPELINE_WAIT_TIMEOUT_SEC,
    POST_OCR_THREADS,
    Q_LLM,
    Q_OCR,
    Q_POST_OCR,
    Q_VALIDATE,
    REDIS_URL,
    RETRY_BASE_SEC,
    RETRY_CAP_SEC,
    RETRY_POLL_SEC,
    RETRY_ZSET,
    VALIDATE_THREADS,
)

__all__ = [
    "CB_FAIL_THRESHOLD",
    "CB_OPEN_SEC",
    "DLQ_LIST",
    "LLM_BATCH_FIRST_WAIT_SEC",
    "LLM_BATCH_INTER_WAIT_SEC",
    "LLM_BATCH_MAX",
    "LLM_THREAD_POOL",
    "OCR_PROCESSES",
    "PIPELINE_MAX_FAILURES_BEFORE_REVIEW",
    "PIPELINE_WAIT_TIMEOUT_SEC",
    "POST_OCR_THREADS",
    "Q_LLM",
    "Q_OCR",
    "Q_POST_OCR",
    "Q_VALIDATE",
    "REDIS_URL",
    "RETRY_BASE_SEC",
    "RETRY_CAP_SEC",
    "RETRY_POLL_SEC",
    "RETRY_ZSET",
    "VALIDATE_THREADS",
]
