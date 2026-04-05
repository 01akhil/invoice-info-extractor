
"""
Lightweight distributed metrics using Redis ONLY.

✔ No local counters (avoids double counting)
✔ Works correctly with multiple workers
✔ Redis = single source of truth
"""

from __future__ import annotations

_REDIS_PREFIX = "pipeline:metric:"


# 🔹 Increment metric in Redis
def _redis_incr(name: str, n: int = 1) -> None:
    try:
        from receipt_pipeline.workers.redis.redis_client import get_redis

        r = get_redis()
        r.incrby(f"{_REDIS_PREFIX}{name}", n)
    except Exception:
        pass


# 🔹 Get all metrics (global snapshot)
def redis_metrics_snapshot() -> dict[str, int]:
    """Aggregated counters from Redis (true global counts)."""
    try:
        from receipt_pipeline.workers.redis.redis_client import get_redis

        r = get_redis()
        out: dict[str, int] = {}

        for key in r.scan_iter(f"{_REDIS_PREFIX}*", count=100):
            name = key[len(_REDIS_PREFIX):] if key.startswith(_REDIS_PREFIX) else key
            try:
                out[name] = int(r.get(key) or 0)
            except (TypeError, ValueError):
                out[name] = 0

        return out

    except Exception:
        return {}


# 🔹 Reset metrics (important before each run)
def reset_redis_metrics() -> None:
    """Clear all Redis metric keys."""
    try:
        from receipt_pipeline.workers.redis.redis_client import get_redis

        r = get_redis()
        keys = list(r.scan_iter(f"{_REDIS_PREFIX}*", count=100))
        if keys:
            r.delete(*keys)
    except Exception:
        pass


# 🔹 Main Metrics Class (Redis-backed)
class PipelineMetrics:
    """
    Distributed metrics collector.

    👉 All increments go to Redis
    👉 No local counters (avoids duplication)
    """

    def inc(self, name: str, n: int = 1) -> None:
        _redis_incr(name, n)

    def snapshot(self) -> dict[str, int]:
        """Return global metrics snapshot from Redis."""
        return redis_metrics_snapshot()


# 🔹 Global instance
METRICS = PipelineMetrics()