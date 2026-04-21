"""DB-derived observability stats for export payloads."""

from __future__ import annotations

from typing import Any

from receipt_pipeline.db.models import ExtractionSource, InvoiceJob, JobStatus
from receipt_pipeline.pipeline.stages import ocr_snapshot_has_regions


def observability_from_invoice_jobs(rows: list[InvoiceJob]) -> dict[str, Any]:
    ocr_done = sum(1 for r in rows if ocr_snapshot_has_regions(r.ocr_snapshot))
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
