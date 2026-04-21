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
from config.logger_setup import get_logger                      # logging

logger = get_logger()

# Lock ensures only ONE thread calculates API timing at a time
_rate_lock = threading.Lock()

# Stores next allowed API call time (monotonic clock for safety)
_next_allowed_monotonic = 0.0


def _pace_before_request() -> None:
    """
    Ensures we don't exceed Gemini RPM (requests per minute).
    Adds delay between API calls if needed.
    """
    global _next_allowed_monotonic

    # Calculate minimum interval between requests
    
    interval = 60.0 / max(float(GEMINI_RPM), 0.5)

    # Lock so multiple threads don't break rate limit logic
    with _rate_lock:
        now = time.monotonic()

        # If we're calling too early → wait
        if now < _next_allowed_monotonic:
            time.sleep(_next_allowed_monotonic - now)
            now = time.monotonic()

        # Schedule next allowed request time
        _next_allowed_monotonic = now + interval


def _is_rate_limit_error(exc: BaseException) -> bool:
    """
    Detect if error is due to rate limiting or quota exceeded.
    Uses string matching because API errors are inconsistent.
    """
    s = str(exc).lower()

    if "429" in s:  # HTTP 429 Too Many Requests
        return True
    if "resource exhausted" in s:
        return True
    if "quota" in s and ("exceed" in s or "exceeded" in s):
        return True
    if "rate limit" in s:
        return True

    return False


def _retry_delay_seconds(exc: BaseException) -> float:
    """
    Extract retry delay from error message if available.
    Otherwise fallback to safe wait (~1 minute).
    """
    text = str(exc)

    # Case 1: "retry in 10s"
    m = re.search(r"retry in ([0-9.]+)\s*s", text, re.I)
    if m:
        return float(m.group(1)) + 0.75  # small buffer

    # Case 2: "seconds: 12"
    m2 = re.search(r"seconds:\s*(\d+)", text)
    if m2:
        return float(m2.group(1)) + 0.75

    # Fallback: wait enough to reset RPM quota
    return 62.0


def gemini_llm_call(prompt: str) -> str:
    """
    Main function to call Gemini API safely.

    Features:
    - Enforces RPM limit (rate control)
    - Retries on quota/rate errors
    - Returns clean text output
    - Never crashes pipeline (returns "" on failure)
    """

    # Ensure at least 1 attempt
    attempts = max(int(GEMINI_429_MAX_RETRIES), 1)

    for attempt in range(attempts):

        # Enforce rate limiting before making API call
        _pace_before_request()

        try:
            # Get Gemini model (configured lazily)
            model = get_generative_model()

            # Call Gemini API
            response = model.generate_content(prompt)

            # Extract text safely (avoid None)
            text = getattr(response, "text", None) or ""

            return text.strip()

        except Exception as e:

            # If it's a rate limit / quota error → retry
            if _is_rate_limit_error(e) and attempt < attempts - 1:

                # Determine how long to wait before retry
                delay = _retry_delay_seconds(e)

                logger.warning(
                    "Gemini rate limit / quota (attempt %s/%s). Sleeping %.1fs then retry.",
                    attempt + 1,
                    attempts,
                    delay,
                )

                time.sleep(delay)
                continue  # retry

            # Non-retryable error OR last attempt
            logger.error("Gemini error: %s", e)

            return ""  # fail gracefully

    # If all retries fail, return empty string
    return ""