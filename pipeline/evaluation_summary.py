"""
Writes ``results/evaluation_summary.json`` for the **latest pipeline run** only.

Reads metrics and outcomes from ``pipeline_export.json`` (same run as export).
Does not write ``evaluation_summary_all.json``, ``pipeline_export_all.*``, or history JSONL.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import RESULTS_DIR
from config.logger_setup import get_logger

logger = get_logger()

EXPORT_JSON = RESULTS_DIR / "pipeline_export.json"
SUMMARY_JSON = RESULTS_DIR / "evaluation_summary.json"


def failure_modes(needs_review: list[dict], non_terminal: list[dict]) -> dict[str, int]:
    c: Counter[str] = Counter()
    for row in needs_review + non_terminal:
        err = (row.get("last_error") or "").strip()
        if not err:
            c["(no last_error)"] += 1
            continue
        key = err[:120] if len(err) > 120 else err
        c[key] += 1
    return dict(c.most_common(25))


def write_summary_from_export(data: dict, *, images_dir: str | None = None) -> dict[str, Any]:
    summary = data.get("summary", {})
    metrics = data.get("metrics", {})
    obs = data.get("observability", {})
    needs = data.get("needs_human_review") or []
    legacy = data.get("legacy_dlq") or []
    other = data.get("non_terminal") or []
    success_n = int(summary.get("success_count", 0))
    failed_review = len(needs) + len(legacy)
    non_term = len(other)
    total = int(summary.get("total_jobs_in_export", success_n + failed_review + non_term))

    out: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_run": True,
        "evaluation_run": {
            "receipt_count": total,
            "export_json": str(EXPORT_JSON),
            "export_csv": str(EXPORT_JSON.with_suffix(".csv")),
        },
        "outcomes": {
            "success": success_n,
            "needs_human_review": len(needs),
            "legacy_dlq": len(legacy),
            "non_terminal_stuck": non_term,
            "failed_or_incomplete": failed_review + non_term,
        },
        "metrics": metrics,
        "metrics_note": (
            "Metrics are for the current pipeline run only (Redis reset each run unless EVAL_KEEP_METRICS=1)."
        ),
        "observability_db": obs,
        "common_failure_modes": failure_modes(list(needs) + list(legacy), list(other)),
        "notes": [
            "Derived from pipeline_export.json for this run.",
            "Human-review items are listed in results/human_review_queue.json, not in valid_invoices.",
        ],
    }
    if images_dir is not None:
        out["evaluation_run"]["images_dir"] = images_dir
    return out


def generate_evaluation_summaries_after_pipeline(
    *,
    images_dir: str | Path | None = None,
    image_filenames: list[str] | None = None,
    data_source: str = "pipeline",
) -> dict[str, Any] | None:
    """
    Read ``pipeline_export.json`` and write ``evaluation_summary.json`` (latest run only).
    """
    if not EXPORT_JSON.is_file():
        logger.warning("Evaluation summary skipped: missing %s", EXPORT_JSON)
        return None

    data = json.loads(EXPORT_JSON.read_text(encoding="utf-8"))
    idir = str(Path(images_dir).resolve()) if images_dir is not None else None
    analysis = write_summary_from_export(data, images_dir=idir)
    er = analysis.setdefault("evaluation_run", {})
    if image_filenames is not None:
        er["image_files"] = image_filenames
    er["data_source"] = data_source

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    logger.info("Wrote evaluation summary (latest run): %s", SUMMARY_JSON)
    return analysis
