"""Application configuration (paths, Redis, submit, env-driven tuning)."""

from config.settings import (
    EVAL_ACCUMULATE_HUMAN_REVIEW,
    GEMINI_MODEL,
    IMAGES_DIR,
    OUTPUTS_DIR,
    PROJECT_ROOT,
    REDIS_URL,
    RESULTS_DIR,
    RESULTS_UPLOAD_DIR,
    SUBMIT_FORM_URL,
    TESSERACT_CMD,
)

__all__ = [
    "EVAL_ACCUMULATE_HUMAN_REVIEW",
    "GEMINI_MODEL",
    "IMAGES_DIR",
    "OUTPUTS_DIR",
    "PROJECT_ROOT",
    "REDIS_URL",
    "RESULTS_DIR",
    "RESULTS_UPLOAD_DIR",
    "SUBMIT_FORM_URL",
    "TESSERACT_CMD",
]
