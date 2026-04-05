"""
Run all pipeline workers: OCR (multiprocessing), post-OCR, LLM pool, validate, retry scheduler.

Used by the orchestrator via ``start_workers``. Requires Redis (see ``REDIS_URL``).
Initializes SQLite under ``data/invoices.db`` (WAL mode for concurrency).
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from typing import Callable

from config.logger_setup import get_logger
from receipt_pipeline.workers.utils.pipeline_log import pl_info

logger = get_logger()


def _ocr_entry(stop_event, worker_id: int) -> None:
    from receipt_pipeline.workers.core.ocr_worker import ocr_worker_loop

    ocr_worker_loop(stop_event, worker_id)


def _retry_entry(stop_event: threading.Event) -> None:
    from receipt_pipeline.workers.redis.redis_client import get_redis
    from receipt_pipeline.workers.retry.retry_ops import retry_scheduler_loop

    r = get_redis()
    pl_info("retry", "scheduler_ready", poll_sec="see RETRY_POLL_SEC", moves_due_jobs_back_to_queues=True)
    retry_scheduler_loop(r, stop_event, logger)


def start_workers(*, run_init_db: bool = True) -> tuple[multiprocessing.Event, threading.Event, list, list, Callable[[], None]]:
    """
    Start OCR processes and I/O worker threads. Returns stop events, handles, and shutdown().
    """
    from receipt_pipeline.workers.config import LLM_THREAD_POOL, OCR_PROCESSES, POST_OCR_THREADS, VALIDATE_THREADS
    from receipt_pipeline.workers.db.session import init_db
    from receipt_pipeline.workers.core.llm_worker import llm_worker_loop
    from receipt_pipeline.workers.core.post_ocr_worker import post_ocr_worker_loop
    from receipt_pipeline.workers.core.validate_worker import validate_worker_loop

    from receipt_pipeline.workers.redis.redis_health import ensure_redis

    ensure_redis()
    if run_init_db:
        init_db()
    pl_info(
        "orchestrator",
        "workers_spawning",
        ocr_processes=OCR_PROCESSES,
        llm_pool=LLM_THREAD_POOL,
        post_ocr_threads=POST_OCR_THREADS,
        validate_threads=VALIDATE_THREADS,
        note="grep_logs_for_[pipeline]",
    )

    stop_mp = multiprocessing.Event()
    stop_threads = threading.Event()

    ocr_procs: list[multiprocessing.Process] = []
    for i in range(OCR_PROCESSES):
        p = multiprocessing.Process(target=_ocr_entry, args=(stop_mp, i), name=f"ocr-{i}", daemon=True)
        p.start()
        ocr_procs.append(p)

    threads: list[threading.Thread] = []

    for _ in range(POST_OCR_THREADS):
        t = threading.Thread(target=post_ocr_worker_loop, args=(stop_threads,), name="post-ocr", daemon=True)
        t.start()
        threads.append(t)

    t_llm = threading.Thread(
        target=llm_worker_loop, args=(stop_threads, LLM_THREAD_POOL), name="llm", daemon=True
    )
    t_llm.start()
    threads.append(t_llm)

    for _ in range(VALIDATE_THREADS):
        t = threading.Thread(target=validate_worker_loop, args=(stop_threads,), name="validate", daemon=True)
        t.start()
        threads.append(t)

    t_retry = threading.Thread(target=_retry_entry, args=(stop_threads,), name="retry-scheduler", daemon=True)
    t_retry.start()
    threads.append(t_retry)

    def shutdown() -> None:
        logger.info("Shutting down pipeline...")
        stop_threads.set()
        stop_mp.set()
        for p in ocr_procs:
            p.join(timeout=5)

    return stop_mp, stop_threads, ocr_procs, threads, shutdown
