"""
Invoice pipeline entrypoint: Redis queues + workers + SQLite (parallel processing only).

Usage:
  python main.py [--pipeline-timeout SEC] [--pipeline-daemon] [--no-submit-form]

By default, after export, valid_invoices are POSTed to the Google Form. Use --no-submit-form or
SUBMIT_AFTER_PIPELINE=0 to skip.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import signal
import sys
import time
from pathlib import Path

from config.logger_setup import get_logger
from config.settings import (
    EVAL_ACCUMULATE_HUMAN_REVIEW,
    IMAGES_DIR,
    RESULTS_DIR,
    SUBMIT_AFTER_PIPELINE,
)

logger = get_logger()

_PIPELINE_EXPORT = RESULTS_DIR / "pipeline_export.json"


def _list_image_files(folder: Path) -> list[Path]:
    exts = {".jpg", ".jpeg", ".png"}
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in exts)


def run_pipeline(*, daemon: bool, wait_timeout_sec: float, submit_form: bool | None = None) -> None:
    from workers.human_review_store import HUMAN_REVIEW_QUEUE_PATH
    from workers.pipelines.export_results import export_pipeline_results
    from workers.pipelines.ingestion import ingest_folder
    from workers.pipelines.job_wait import wait_for_terminal_jobs
    from workers.pipelines.run_pipeline import start_workers
    from workers.redis.redis_client import get_redis
    from workers.utils.metrics import reset_redis_metrics
    from workers.utils.pipeline_log import pl_info

    if os.environ.get("EVAL_KEEP_METRICS", "").lower() not in ("1", "true", "yes"):
        reset_redis_metrics()

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if not EVAL_ACCUMULATE_HUMAN_REVIEW:
        HUMAN_REVIEW_QUEUE_PATH.write_text("[]", encoding="utf-8")
        logger.info(
            "Reset %s for this run (set EVAL_ACCUMULATE_HUMAN_REVIEW=1 to merge across runs).",
            HUMAN_REVIEW_QUEUE_PATH.name,
        )

    pl_info(
        "orchestrator",
        "phase_start_workers",
        daemon=daemon,
        wait_timeout_sec=wait_timeout_sec,
        images_dir=str(IMAGES_DIR),
    )
    _, _, _, _, shutdown_workers = start_workers(run_init_db=True)
    time.sleep(1.5)
    pl_info("orchestrator", "phase_ingest", after_sleep_sec=1.5)
    r = get_redis()
    ids = ingest_folder(r, IMAGES_DIR)

    logger.info("Pipeline ingested %s job(s).", len(ids))

    if not ids:
        pl_info("orchestrator", "no_images_abort", folder=str(IMAGES_DIR))
        logger.warning("No images found in %s — nothing to process.", IMAGES_DIR)
        shutdown_workers()
        return

    do_submit = SUBMIT_AFTER_PIPELINE if submit_form is None else submit_form

    if not daemon:
        try:
            ok, needs_review = wait_for_terminal_jobs(ids, timeout_sec=wait_timeout_sec)
            logger.info(
                "Pipeline finished: success=%s needs_human_review=%s (see results/human_review_queue.json)",
                len(ok),
                len(needs_review),
            )
        except TimeoutError as e:
            pl_info("orchestrator", "wait_timeout", error=str(e))
            logger.error("%s", e)
        try:
            export_pipeline_results(_PIPELINE_EXPORT, job_ids=ids)
            logger.info("Exported results: %s", _PIPELINE_EXPORT)
            try:
                from pipeline.evaluation_summary import generate_evaluation_summaries_after_pipeline

                generate_evaluation_summaries_after_pipeline(
                    images_dir=IMAGES_DIR,
                    image_filenames=[p.name for p in _list_image_files(IMAGES_DIR)],
                    data_source="main_pipeline",
                )
            except Exception as e:
                logger.exception("Evaluation summary failed (export still valid): %s", e)
            if do_submit:
                try:
                    from submit.service import submit_from_export

                    submit_from_export(_PIPELINE_EXPORT)
                except Exception as e:
                    logger.exception("Google Form submit failed (export still valid): %s", e)
        except Exception as e:
            logger.exception("Export failed: %s", e)
        pl_info("orchestrator", "phase_shutdown_workers", reason="one_shot_complete")
        shutdown_workers()
        logger.info("Workers stopped.")
        return

    pl_info(
        "orchestrator",
        "daemon_mode_no_auto_wait",
        hint="ingest_done_workers_keep_running_Ctrl+C_to_stop",
    )
    logger.info(
        "Daemon mode: workers keep running. Optional API: uvicorn workers.api:app --port 8765. Ctrl+C to stop."
    )

    def _shutdown(*_a) -> None:
        shutdown_workers()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        _shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Invoice OCR pipeline (Redis + parallel workers).",
    )
    parser.add_argument(
        "--pipeline-daemon",
        action="store_true",
        help="Keep workers running after ingest (default: wait, export, exit).",
    )
    parser.add_argument(
        "--pipeline-timeout",
        type=float,
        default=None,
        help="Seconds to wait for all jobs to finish (default: env PIPELINE_WAIT_TIMEOUT_SEC or 3600).",
    )
    form_group = parser.add_mutually_exclusive_group()
    form_group.add_argument(
        "--submit-form",
        action="store_true",
        help="Force Google Form submit after export (overrides SUBMIT_AFTER_PIPELINE=0).",
    )
    form_group.add_argument(
        "--no-submit-form",
        action="store_true",
        help="Skip posting valid_invoices to Google Form after export.",
    )
    args = parser.parse_args()

    from workers.config import PIPELINE_WAIT_TIMEOUT_SEC

    to = float(args.pipeline_timeout) if args.pipeline_timeout is not None else PIPELINE_WAIT_TIMEOUT_SEC
    submit: bool | None
    if args.no_submit_form:
        submit = False
    elif args.submit_form:
        submit = True
    else:
        submit = None

    run_pipeline(
        daemon=args.pipeline_daemon,
        wait_timeout_sec=to,
        submit_form=submit,
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
