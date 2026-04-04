"""Verify Redis is reachable before starting workers (clear errors for operators)."""

from __future__ import annotations

import time

from workers.config import REDIS_URL


def ensure_redis(*, timeout_sec: float = 30.0, poll_sec: float = 0.5) -> None:
    """
    Block until `PING` succeeds or timeout.
    Raises RuntimeError with actionable hint if Redis is unavailable.
    """
    from workers.redis.redis_client import get_redis

    deadline = time.monotonic() + timeout_sec
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = get_redis()
            r.ping()
            return
        except Exception as e:
            last = e
            time.sleep(poll_sec)
    msg = (
        f"Redis is not reachable at {REDIS_URL!r} (last error: {last}). "
        "Start Redis first, e.g. from the project folder run:  docker compose up -d"
    )
    raise RuntimeError(msg) from last
