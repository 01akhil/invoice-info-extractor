"""
Gemini generate_content with:
- Thread-safe pacing to respect requests-per-minute (free tier ~15 RPM).
- Automatic retry on HTTP 429 / quota with delays parsed from errors when possible.
"""

from __future__ import annotations

import re
import threading
import time

from config.settings import GEMINI_429_MAX_RETRIES, GEMINI_RPM
from receipt_pipeline.llm.client import get_generative_model
from config.logger_setup import get_logger

logger = get_logger()

_rate_lock = threading.Lock()
_next_allowed_monotonic = 0.0
def _pace_before_request() -> None:
    """Space out API calls to stay under GEMINI_RPM (requests per minute)."""
    global _next_allowed_monotonic
    interval = 60.0 / max(float(GEMINI_RPM), 0.5)
    with _rate_lock:
        now = time.monotonic()
        if now < _next_allowed_monotonic:
            time.sleep(_next_allowed_monotonic - now)
            now = time.monotonic()
        _next_allowed_monotonic = now + interval

def _is_rate_limit_error(exc: BaseException) -> bool:
    s = str(exc).lower()
    if "429" in s:
        return True
    if "resource exhausted" in s:
        return True
    if "quota" in s and ("exceed" in s or "exceeded" in s):
        return True
    if "rate limit" in s:
        return True
    return False


def _retry_delay_seconds(exc: BaseException) -> float:
    """Parse server hint, else wait long enough for free-tier per-minute quota."""
    text = str(exc)
    m = re.search(r"retry in ([0-9.]+)\s*s", text, re.I)
    if m:
        return float(m.group(1)) + 0.75
    m2 = re.search(r"seconds:\s*(\d+)", text)
    if m2:
        return float(m2.group(1)) + 0.75
    return 62.0


def gemini_llm_call(prompt: str) -> str:
    """
    Call Gemini with RPM pacing and retries on 429/quota errors.
    Returns response text, or "" if all attempts fail.
    """
    attempts = max(int(GEMINI_429_MAX_RETRIES), 1)
    for attempt in range(attempts):
        _pace_before_request()
        try:
            model = get_generative_model()
            response = model.generate_content(prompt)
            text = getattr(response, "text", None) or ""
            return text.strip()
        except Exception as e:
            if _is_rate_limit_error(e) and attempt < attempts - 1:
                delay = _retry_delay_seconds(e)
                logger.warning(
                    "Gemini rate limit / quota (attempt %s/%s). Sleeping %.1fs then retry.",
                    attempt + 1,
                    attempts,
                    delay,
                )
                time.sleep(delay)
                continue
            logger.error("Gemini error: %s", e)
            return ""
    return ""
