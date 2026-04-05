"""Export pipeline DB results to JSON (parity with sequential `final_answer.json` shape)."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from receipt_pipeline.workers.db.models import ExtractionSource, InvoiceJob, JobStatus
from receipt_pipeline.workers.db.session import SessionLocal
from receipt_pipeline.workers.utils.metrics import METRICS
from receipt_pipeline.workers.utils.pipeline_log import pl_info
from config.logger_setup import get_logger

logger = get_logger()


def fetch_jobs_by_ids(job_ids: list[str]) -> list[InvoiceJob]:
    if not job_ids:
        return []
    session = SessionLocal()
    try:
        stmt = select(InvoiceJob).where(InvoiceJob.job_id.in_(job_ids))
        return list(session.scalars(stmt).all())
    finally:
        session.close()


def _row_to_dict(r: InvoiceJob) -> dict[str, Any]:
    return {
        "job_id": r.job_id,
        "file": r.image_path,
        "vendor": r.vendor,
        "date": r.invoice_date,
        "total": r.total_amount,
        "confidence": r.confidence,
        "source": r.source,
        "status": r.status,
        "retry_count": r.retry_count,
        "last_error": r.last_error,
    }


def _observability_from_rows(rows: list[InvoiceJob]) -> dict[str, Any]:
    """DB-derived stats for OCR vs rule vs LLM paths (per-job truth)."""
    ocr_done = sum(1 for r in rows if r.ocr_snapshot)
    by_source: dict[str, int] = {}
    for r in rows:
        s = r.source or "unset"
        by_source[s] = by_source.get(s, 0) + 1
    llm_sources = {ExtractionSource.OCR_LLM.value, ExtractionSource.LLM.value}
    rule_only_success = sum(
        1
        for r in rows
        if r.status == JobStatus.SUCCESS.value and (r.source == ExtractionSource.OCR_RULE.value)
    )
    llm_sourced = sum(1 for r in rows if r.source in llm_sources)
    return {
        "jobs_with_ocr_snapshot": ocr_done,
        "terminal_success_with_rule_extraction_only": rule_only_success,
        "jobs_with_llm_sourced_extraction": llm_sourced,
        "source_histogram": by_source,
    }


def _write_csv(path: Path, flat_rows: list[dict[str, Any]]) -> None:
    if not flat_rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(flat_rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(flat_rows)


def export_pipeline_results(
    out_path: Path,
    *,
    job_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Write JSON with successful invoices, NEEDS_REVIEW (and legacy DLQ) rows.
    If job_ids is None, exports all rows from the table (use with care).
    """
    session = SessionLocal()
    try:
        if job_ids is None:
            stmt = select(InvoiceJob)
        else:
            stmt = select(InvoiceJob).where(InvoiceJob.job_id.in_(job_ids))
        rows = list(session.scalars(stmt).all())
    finally:
        session.close()

    success = [_row_to_dict(r) for r in rows if r.status == JobStatus.SUCCESS.value]
    needs_review = [_row_to_dict(r) for r in rows if r.status == JobStatus.NEEDS_REVIEW.value]
    legacy_dlq = [_row_to_dict(r) for r in rows if r.status == JobStatus.DLQ.value]
    other = [
        _row_to_dict(r)
        for r in rows
        if r.status
        not in (
            JobStatus.SUCCESS.value,
            JobStatus.NEEDS_REVIEW.value,
            JobStatus.DLQ.value,
        )
    ]

    metrics_snap = METRICS.snapshot()
    obs = _observability_from_rows(rows)
    # Same count as observability.terminal_success_with_rule_extraction_only (not raw Tesseract completions).
    metrics_out = dict(metrics_snap)
    metrics_out["ocr_success"] = obs["terminal_success_with_rule_extraction_only"]
    payload: dict[str, Any] = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "valid_invoices": success,
        "needs_human_review": needs_review,
        "legacy_dlq": legacy_dlq,
        "non_terminal": other,
        "summary": {
            "success_count": len(success),
            "needs_human_review_count": len(needs_review),
            "legacy_dlq_count": len(legacy_dlq),
            "non_terminal_count": len(other),
            "human_review_file": "results/human_review_queue.json",
            "total_jobs_in_export": len(rows),
        },
        "metrics": metrics_out,
        "metrics_scope": "current_pipeline_run",
        "metrics_interpretation": {
            "scope": "Counters reset at each pipeline start (unless EVAL_KEEP_METRICS=1). Values match this export batch, not prior runs.",
            "ocr_success": "Terminal SUCCESS jobs with extraction source OCR_RULE (rules path, no LLM); matches observability.terminal_success_with_rule_extraction_only.",
            "ocr_fail": "OCR stage raised before snapshot stored.",
            "llm_invocations": "Total Gemini API calls (each batch call counts as 1).",
            "llm_batch_calls": "Batch API calls (multiple invoices per request when batching applies).",
            "llm_single_calls": "Single-invoice Gemini API calls (fallback or batch item recovery).",
            "llm_fallback_routed": "Jobs routed to LLM after rules due to low confidence.",
            # "validation_fail": "Validation rejections (may schedule LLM retry).",
            "retry_scheduled": "Backoff retries scheduled onto the retry ZSET.",
            "success_total": "Jobs marked SUCCESS after validation.",
        },
        "observability": obs,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    csv_path = out_path.with_suffix(".csv")
    _write_csv(csv_path, [_row_to_dict(r) for r in rows])
    pl_info("orchestrator", "export_csv_written", path=str(csv_path), rows=len(rows))
    pl_info(
        "orchestrator",
        "export_written",
        path=str(out_path),
        success=payload["summary"]["success_count"],
        needs_human_review=payload["summary"]["needs_human_review_count"],
        non_terminal=payload["summary"]["non_terminal_count"],
        llm_invocations=metrics_snap.get("llm_invocations"),
        ocr_success=metrics_out.get("ocr_success"),
    )
    logger.info("Pipeline export written: %s", out_path)
    return payload



