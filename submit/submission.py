import time
import requests
from config import FORM_URL, MAX_RETRIES
from config.logger_setup import setup_logger

logger = setup_logger()

def submit_invoice(form_data: dict, max_retries: int = MAX_RETRIES, base_delay: float = 0.5) -> bool:
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(FORM_URL, data=form_data, timeout=15)
            if response.status_code == 200:
                return True
            else:
                logger.warning("Attempt %d/%d: Failed to submit invoice '%s' | Status code: %d",
                               attempt, max_retries, form_data.get("vendor", ""), response.status_code)
        except requests.exceptions.RequestException as e:
            logger.error("Attempt %d/%d: Exception submitting invoice '%s': %s",
                         attempt, max_retries, form_data.get("vendor", ""), e)

        wait_time = base_delay * (2 ** (attempt - 1))
        logger.info("Waiting %.1f seconds before retrying...", wait_time)
        time.sleep(wait_time)
    return False