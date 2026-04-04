"""Dispatch validated invoices to Google Form (shared implementation in ``submit`` package)."""

from __future__ import annotations

import logging

from submit.service import submit_from_export

from .config import BASE_DELAY, MAX_RETRIES

logger = logging.getLogger(__name__)


def dispatch_invoices(json_file_path: str, delay: float = BASE_DELAY, max_retries: int = MAX_RETRIES) -> None:
    """Submit ``valid_invoices`` from JSON (sequential ``final_answer.json`` or pipeline export)."""
    report = submit_from_export(json_file_path, delay_between=delay, max_retries=max_retries)
    if report.skipped_no_valid:
        logger.info("No invoices to submit. Exiting.")
