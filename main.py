from __future__ import annotations

import argparse
import multiprocessing
import sys
from pathlib import Path

# Allow `python main.py` without prior `pip install -e .` (adds src/ to path).
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config.settings import PIPELINE_WAIT_TIMEOUT_SEC
from receipt_pipeline.workers.orchestration.orchestrator import run_pipeline

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