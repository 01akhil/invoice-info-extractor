# submission.py
import requests
import time
import logging

from .config import FORM_URL, TIMEOUT, MAX_RETRIES, BASE_DELAY

logger = logging.getLogger(__name__)

def send_invoice(form_data: dict, max_retries: int = MAX_RETRIES, base_delay: float = BASE_DELAY) -> bool:
    """
    Submits a single invoice with retry logic and exponential backoff.
    """
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(FORM_URL, data=form_data, timeout=TIMEOUT)
            if response.status_code == 200:
                return True
            else:
                logger.warning(
                    "Attempt %d/%d: Failed to submit invoice '%s' | Status code: %d",
                    attempt, max_retries, form_data.get("vendor", ""), response.status_code
                )
        except requests.exceptions.RequestException as e:
            logger.error(
                "Attempt %d/%d: Error submitting invoice '%s': %s",
                attempt, max_retries, form_data.get("vendor", ""), e
            )

        wait_time = base_delay * (2 ** (attempt - 1))
        logger.info("Waiting %.1f seconds before retrying...", wait_time)
        time.sleep(wait_time)

    return False