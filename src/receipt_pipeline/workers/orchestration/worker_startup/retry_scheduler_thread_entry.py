"""Thread target: Redis ZSET retry scheduler."""
# This module defines the function that will run inside a background thread
# responsible for handling retry logic using Redis sorted sets (ZSET)

from __future__ import annotations  # enables modern type hints

import threading  # used for thread control (stop_event)

from config.logger_setup import get_logger  # logging system
from receipt_pipeline.redis_queue import get_redis  # Redis connection
from receipt_pipeline.workers.retry.retry_ops import retry_scheduler_loop 
from receipt_pipeline.workers.utils.pipeline_log import pl_info 

logger = get_logger()


def retry_scheduler_thread_entry(stop_event: threading.Event) -> None:
    """
    Entry point for retry scheduler thread.

    This function:
    - Connects to Redis
    - Logs that scheduler is ready
    - Starts retry loop that continuously processes delayed jobs
    """

    # Get Redis client (used for queues + retry ZSET)
    r = get_redis()

    # Log that retry scheduler is active
    pl_info(
        "retry",
        "scheduler_ready",
        poll_sec="see RETRY_POLL_SEC",  # polling interval (configured elsewhere)
        moves_due_jobs_back_to_queues=True,  # explains what this worker does
    )

    # Start the retry scheduler loop (runs until stop_event is set)
    retry_scheduler_loop(r, stop_event, logger)