"""
Single source of truth for environment-driven settings.

Load order: optional ``.env`` in project root (via python-dotenv), then process environment.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

# --- Paths ---
TESSERACT_CMD = os.environ.get(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
)

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.1-flash-lite-preview",
)

GEMINI_RPM = int(os.environ.get("GEMINI_RPM", "12"))
GEMINI_429_MAX_RETRIES = int(os.environ.get("GEMINI_429_MAX_RETRIES", "12"))

IMAGES_DIR = Path(os.environ.get("IMAGES_DIR", str(PROJECT_ROOT / "images"))).resolve()
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_UPLOAD_DIR = RESULTS_DIR / "upload"

# --- Redis & pipeline queues ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

Q_OCR = os.environ.get("Q_OCR", "invoice:ocr")
Q_POST_OCR = os.environ.get("Q_POST_OCR", "invoice:post_ocr")
Q_LLM = os.environ.get("Q_LLM", "invoice:llm")
Q_VALIDATE = os.environ.get("Q_VALIDATE", "invoice:validate")

RETRY_ZSET = os.environ.get("RETRY_ZSET", "invoice:retry:due")
DLQ_LIST = os.environ.get("DLQ_LIST", "invoice:dlq")

OCR_PROCESSES = int(os.environ.get("OCR_PROCESSES", "4"))
LLM_BATCH_MAX = int(os.environ.get("LLM_BATCH_MAX", "3"))
LLM_BATCH_FIRST_WAIT_SEC = float(os.environ.get("LLM_BATCH_FIRST_WAIT_SEC", "5"))
LLM_BATCH_INTER_WAIT_SEC = float(os.environ.get("LLM_BATCH_INTER_WAIT_SEC", "1.0"))
LLM_THREAD_POOL = int(os.environ.get("LLM_THREAD_POOL", "1"))
POST_OCR_THREADS = int(os.environ.get("POST_OCR_THREADS", "2"))
VALIDATE_THREADS = int(os.environ.get("VALIDATE_THREADS", "2"))
RETRY_POLL_SEC = float(os.environ.get("RETRY_POLL_SEC", "0.5"))

RETRY_BASE_SEC = float(os.environ.get("RETRY_BASE_SEC", "5.0"))
RETRY_CAP_SEC = float(os.environ.get("RETRY_CAP_SEC", "900.0"))

PIPELINE_WAIT_TIMEOUT_SEC = float(os.environ.get("PIPELINE_WAIT_TIMEOUT_SEC", "3600"))
PIPELINE_MAX_FAILURES_BEFORE_REVIEW = int(os.environ.get("PIPELINE_MAX_FAILURES_BEFORE_REVIEW", "2"))

CB_FAIL_THRESHOLD = int(os.environ.get("CB_FAIL_THRESHOLD", "5"))
CB_OPEN_SEC = int(os.environ.get("CB_OPEN_SEC", "60"))

# --- Google Form (submit) — only ``valid_invoices`` from exports are posted, never human_review ---

SUBMIT_FORM_URL = os.environ.get(
    "SUBMIT_FORM_URL",
    "https://docs.google.com/forms/d/e/1FAIpQLScpamHrcS3vWr4-uWVqxw9Vr9vU74cJmhdFgor0yLPoCgkbWA/formResponse",
)

SUBMIT_ENTRY_VENDOR = os.environ.get("SUBMIT_ENTRY_VENDOR", "entry.185959394")
SUBMIT_ENTRY_DATE = os.environ.get("SUBMIT_ENTRY_DATE", "entry.1839803201")
SUBMIT_ENTRY_TOTAL = os.environ.get("SUBMIT_ENTRY_TOTAL", "entry.552729475")
SUBMIT_MAX_RETRIES = int(os.environ.get("SUBMIT_MAX_RETRIES", "3"))
SUBMIT_DELAY = float(os.environ.get("SUBMIT_DELAY", "0.2"))
SUBMIT_TIMEOUT = float(os.environ.get("SUBMIT_TIMEOUT", "15"))
# Date field sent to Google: ``iso`` = YYYY-MM-DD (required for Forms "Date" questions; avoids HTTP 400).
# Use ``dmy`` for DD/MM/YYYY only if the form uses a short-answer text field, not a Date picker.
SUBMIT_DATE_FORMAT = os.environ.get("SUBMIT_DATE_FORMAT", "iso").strip().lower()
# After a one-shot pipeline run, POST valid_invoices to the form (set 0 or use --no-submit-form to skip).
SUBMIT_AFTER_PIPELINE = os.environ.get("SUBMIT_AFTER_PIPELINE", "1").lower() not in (
    "0",
    "false",
    "no",
    "off",
)

# --- Evaluation / pipeline artifacts ---
# When false (default), each pipeline run starts with an empty human_review_queue.json.
EVAL_ACCUMULATE_HUMAN_REVIEW = os.environ.get("EVAL_ACCUMULATE_HUMAN_REVIEW", "").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
