from __future__ import annotations
import os
import signal
import sys
import time
from pathlib import Path
from config.logger_setup import get_logger
from config.settings import IMAGES_DIR, RESULTS_DIR, SUBMIT_AFTER_PIPELINE, EVAL_ACCUMULATE_HUMAN_REVIEW
from workers.utils.pipeline_utils import list_image_files, reset_human_review_queue
from workers.tasks.run_pipeline import start_workers
from workers.redis.redis_client import get_redis
from workers.utils.pipeline_log import pl_info
from workers.utils.metrics import reset_redis_metrics

logger = get_logger()
_PIPELINE_EXPORT = RESULTS_DIR / "pipeline_export.json"

def run_pipeline(*, daemon: bool, wait_timeout_sec: float, submit_form: bool | None = None) -> None:
    from workers.tasks.export_results import export_pipeline_results
    from workers.tasks.ingestion import ingest_folder
    from workers.tasks.job_wait import wait_for_terminal_jobs
    from workers.config import PIPELINE_WAIT_TIMEOUT_SEC
    from workers.human_review_store import HUMAN_REVIEW_QUEUE_PATH

    # Reset metrics
    if os.environ.get("EVAL_KEEP_METRICS", "").lower() not in ("1", "true", "yes"):
        reset_redis_metrics()

    # Ensure folders exist
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Reset human review queue if needed
    if not EVAL_ACCUMULATE_HUMAN_REVIEW:
        reset_human_review_queue(HUMAN_REVIEW_QUEUE_PATH)
        logger.info("Reset %s for this run.", HUMAN_REVIEW_QUEUE_PATH.name)

    # Start workers
    pl_info("orchestrator", "phase_start_workers", daemon=daemon, wait_timeout_sec=wait_timeout_sec, images_dir=str(IMAGES_DIR))
    _, _, _, _, shutdown_workers = start_workers(run_init_db=True)
    time.sleep(1.5)

    # Ingest images
    pl_info("orchestrator", "phase_ingest", after_sleep_sec=1.5)
    r = get_redis()
    job_ids = ingest_folder(r, IMAGES_DIR)
    logger.info("Pipeline ingested %s job(s).", len(job_ids))

    if not job_ids:
        pl_info("orchestrator", "no_images_abort", folder=str(IMAGES_DIR))
        logger.warning("No images found in %s — nothing to process.", IMAGES_DIR)
        shutdown_workers()
        return

    do_submit = SUBMIT_AFTER_PIPELINE if submit_form is None else submit_form

    if not daemon:
        try:
            ok, needs_review = wait_for_terminal_jobs(job_ids, timeout_sec=wait_timeout_sec)
            logger.info(
                "Pipeline finished: success=%s needs_human_review=%s",
                len(ok),
                len(needs_review),
            )
        except TimeoutError as e:
            pl_info("orchestrator", "wait_timeout", error=str(e))
            logger.error("%s", e)

        # Export results
        try:
            export_pipeline_results(_PIPELINE_EXPORT, job_ids=job_ids)
            logger.info("Exported results: %s", _PIPELINE_EXPORT)

            # Evaluation summary
            try:
                from pipeline.evaluation.evaluation_summary import generate_evaluation_summaries_after_pipeline
                generate_evaluation_summaries_after_pipeline(
                    images_dir=IMAGES_DIR,
                    image_filenames=[p.name for p in list_image_files(IMAGES_DIR)],
                    data_source="main_pipeline",
                )
            except Exception as e:
                logger.exception("Evaluation summary failed (export still valid): %s", e)

            # Google Form submission
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

    # Daemon mode: keep workers running
    pl_info("orchestrator", "daemon_mode_no_auto_wait", hint="ingest_done_workers_keep_running_Ctrl+C_to_stop")
    logger.info("Daemon mode: workers keep running. Ctrl+C to stop.")

    def _shutdown(*_args):
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