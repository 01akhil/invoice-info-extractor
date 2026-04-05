"""Simple circuit breaker for LLM calls (in-process)."""

from __future__ import annotations

import threading
import time


class CircuitBreaker:
    def __init__(self, fail_threshold: int = 5, open_seconds: float = 60.0) -> None:
        self._fail_threshold = fail_threshold
        self._open_seconds = open_seconds
        self._failures = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            return time.time() >= self._open_until

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._fail_threshold:
                self._open_until = time.time() + self._open_seconds
                self._failures = 0

    def seconds_until_half_open(self) -> float:
        with self._lock:
            return max(0.0, self._open_until - time.time())
