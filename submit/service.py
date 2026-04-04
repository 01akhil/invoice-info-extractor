"""
Google Form submission for pipeline exports.

Submits only ``valid_invoices`` (validated SUCCESS rows). Records in
``needs_human_review`` / ``legacy_dlq`` are never sent.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from config.logger_setup import get_logger

from .config import ENTRY_DATE, ENTRY_TOTAL, ENTRY_VENDOR, FORM_URL, MAX_RETRIES, SUBMIT_DELAY, TIMEOUT

logger = get_logger()

# Google often serves the confirmation HTML with 200; some clients get redirects (handled by requests).
_FORM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


@dataclass
class SubmitReport:
    """Outcome of a batch submit."""

    source_file: str
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped_no_valid: bool = False
    errors: list[str] = field(default_factory=list)


def _normalize_invoice_row(inv: dict[str, Any]) -> dict[str, str]:
    """Build form field map from export row (pipeline or sequential final_answer)."""
    vendor = str(inv.get("vendor") or "").strip()
    date = str(inv.get("date") or inv.get("invoice_date") or "").strip()
    total = inv.get("total")
    if total is None:
        total_s = ""
    else:
        total_s = str(total).strip()
    return {
        ENTRY_VENDOR: vendor,
        ENTRY_DATE: date,
        ENTRY_TOTAL: total_s,
    }


def _post_with_retry(form_data: dict[str, str], *, max_retries: int, base_delay: float) -> bool:
    label = form_data.get(ENTRY_VENDOR, "")
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                FORM_URL,
                data=form_data,
                timeout=TIMEOUT,
                headers=_FORM_HEADERS,
            )
            if response.ok:
                return True
            snippet = (response.text or "")[:300].replace("\n", " ")
            logger.warning(
                "Form submit attempt %d/%d failed | vendor=%s | status=%s | body[:300]=%s",
                attempt,
                max_retries,
                label,
                response.status_code,
                snippet,
            )
        except requests.RequestException as e:
            logger.error("Form submit attempt %d/%d error | vendor=%s | %s", attempt, max_retries, label, e)
        time.sleep(base_delay * (2 ** (attempt - 1)))
    return False


def load_valid_invoices_only(export_path: Path) -> tuple[list[dict[str, Any]], SubmitReport]:
    """
    Load JSON and return only ``valid_invoices`` (excludes human-review queue by design).

    Supports:
    - ``pipeline_export.json`` (``valid_invoices`` key; excludes ``needs_human_review`` by design)
    - ``final_answer.json`` from legacy sequential mode (same key)
    """
    report = SubmitReport(source_file=str(export_path))
    if not export_path.is_file():
        report.errors.append(f"file not found: {export_path}")
        return [], report

    try:
        data = json.loads(export_path.read_text(encoding="utf-8"))
    except Exception as e:
        report.errors.append(str(e))
        return [], report

    valid = data.get("valid_invoices")
    if not isinstance(valid, list):
        report.errors.append("missing or invalid valid_invoices array")
        return [], report

    # Extra safety: never submit non-success rows if present
    safe: list[dict[str, Any]] = []
    for row in valid:
        if not isinstance(row, dict):
            continue
        st = row.get("status")
        if st is not None and str(st).strip().upper() != "SUCCESS":
            continue
        safe.append(row)

    if not safe:
        report.skipped_no_valid = True
        return [], report

    return safe, report


def submit_from_export(
    export_path: str | Path,
    *,
    delay_between: float | None = None,
    max_retries: int | None = None,
) -> SubmitReport:
    """
    POST each valid invoice to the configured Google Form.

    Parameters
    ----------
    export_path:
        Path to ``pipeline_export.json`` (or compatible JSON with ``valid_invoices``).
    delay_between:
        Pause after each invoice (rate limiting). Defaults to ``SUBMIT_DELAY``.
    max_retries:
        Retries per invoice. Defaults to ``MAX_RETRIES``.
    """
    path = Path(export_path)
    delay = SUBMIT_DELAY if delay_between is None else delay_between
    retries = MAX_RETRIES if max_retries is None else max_retries

    rows, report = load_valid_invoices_only(path)
    if report.errors and not rows:
        logger.error("Submit aborted: %s", report.errors)
        return report

    if report.skipped_no_valid:
        logger.warning("No valid_invoices to submit from %s", path)
        return report

    report.attempted = len(rows)
    logger.info("Submitting %s invoice(s) from %s (human-review rows excluded)", len(rows), path)

    for idx, inv in enumerate(rows, start=1):
        form_data = _normalize_invoice_row(inv)
        ok = _post_with_retry(form_data, max_retries=retries, base_delay=delay)
        if ok:
            report.succeeded += 1
            logger.info("[%d/%d] Submitted: %s", idx, len(rows), form_data.get(ENTRY_VENDOR, ""))
        else:
            report.failed += 1
            logger.error("[%d/%d] Failed after retries: %s", idx, len(rows), form_data.get(ENTRY_VENDOR, ""))
        time.sleep(delay)

    logger.info(
        "Form submit finished: ok=%s failed=%s (source=%s)",
        report.succeeded,
        report.failed,
        path,
    )
    return report
