from __future__ import annotations

import redis

from workers.config import REDIS_URL


def get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=10,
        socket_timeout=120,
        health_check_interval=30,
    )
