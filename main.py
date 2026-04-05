from __future__ import annotations

import argparse
import multiprocessing
import sys
from pathlib import Path

# Allow `python main.py` without prior `pip install -e .` (adds src/ to path).
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config.settings import PIPELINE_WAIT_TIMEOUT_SEC, RESULTS_DIR
from receipt_pipeline.workers.orchestration.orchestrator import run_pipeline

_DEFAULT_EXPORT = RESULTS_DIR / "pipeline_export.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Invoice OCR pipeline: process images and submit to Google Form, or submit-only from export JSON.",
    )
    parser.add_argument(
        "--submit-only",
        action="store_true",
        help="Skip the pipeline; POST valid_invoices from results/pipeline_export.json to the Google Form only.",
    )
    args = parser.parse_args()

    if args.submit_only:
        from receipt_pipeline.submission.service import submit_from_export

        report = submit_from_export(_DEFAULT_EXPORT)
        if report.errors and report.attempted == 0:
            sys.exit(1)
        sys.exit(0 if report.failed == 0 else 2)

    run_pipeline(wait_timeout_sec=PIPELINE_WAIT_TIMEOUT_SEC)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
