from __future__ import annotations
import argparse
import multiprocessing
from config.settings import PIPELINE_WAIT_TIMEOUT_SEC
from workers.tasks.orchestrator import run_pipeline

def main() -> None:
    parser = argparse.ArgumentParser(description="Invoice OCR pipeline (Redis + parallel workers).")
    parser.add_argument("--pipeline-daemon", action="store_true", help="Keep workers running after ingest.")
    parser.add_argument("--pipeline-timeout", type=float, default=None, help="Seconds to wait for all jobs to finish.")
    form_group = parser.add_mutually_exclusive_group()
    form_group.add_argument("--submit-form", action="store_true", help="Force Google Form submit after export.")
    form_group.add_argument("--no-submit-form", action="store_true", help="Skip Google Form submit after export.")
    args = parser.parse_args()

    timeout = args.pipeline_timeout or PIPELINE_WAIT_TIMEOUT_SEC
    submit: bool | None = None
    if args.no_submit_form:
        submit = False
    elif args.submit_form:
        submit = True

    run_pipeline(daemon=args.pipeline_daemon, wait_timeout_sec=timeout, submit_form=submit)

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()