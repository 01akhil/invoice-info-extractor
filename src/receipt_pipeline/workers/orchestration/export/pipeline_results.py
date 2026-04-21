"""Export pipeline DB results to JSON (parity with sequential `final_answer.json` shape)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from receipt_pipeline.db.models import InvoiceJob, JobStatus
from receipt_pipeline.db.session import SessionLocal
from receipt_pipeline.workers.orchestration.export.invoice_row_dict import invoice_row_to_flat_dict
from receipt_pipeline.workers.orchestration.export.observability import observability_from_invoice_jobs
from receipt_pipeline.workers.orchestration.export.write_csv import write_flat_dict_rows_csv
from receipt_pipeline.workers.utils.metrics import METRICS
from receipt_pipeline.workers.utils.pipeline_log import pl_info
from config.logger_setup import get_logger

logger = get_logger()


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

    success = [invoice_row_to_flat_dict(r) for r in rows if r.status == JobStatus.SUCCESS.value]
    needs_review = [invoice_row_to_flat_dict(r) for r in rows if r.status == JobStatus.NEEDS_REVIEW.value]
    legacy_dlq = [invoice_row_to_flat_dict(r) for r in rows if r.status == JobStatus.DLQ.value]
    other = [
        invoice_row_to_flat_dict(r)
        for r in rows
        if r.status
        not in (
            JobStatus.SUCCESS.value,
            JobStatus.NEEDS_REVIEW.value,
            JobStatus.DLQ.value,
        )
    ]

    metrics_snap = METRICS.snapshot()
    obs = observability_from_invoice_jobs(rows)
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
            "retry_scheduled": "Backoff retries scheduled onto the retry ZSET.",
            "success_total": "Jobs marked SUCCESS after validation.",
        },
        "observability": obs,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    csv_path = out_path.with_suffix(".csv")
    write_flat_dict_rows_csv(csv_path, [invoice_row_to_flat_dict(r) for r in rows])
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
