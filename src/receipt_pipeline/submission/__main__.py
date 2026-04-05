"""CLI: python -m receipt_pipeline.submission [--export PATH] (requires pip install -e . or PYTHONPATH=src)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config.settings import RESULTS_DIR


def main() -> None:
    default_export = RESULTS_DIR / "pipeline_export.json"
    ap = argparse.ArgumentParser(description="Submit valid_invoices from export JSON to Google Form.")
    ap.add_argument(
        "--export",
        type=Path,
        default=default_export,
        help=f"JSON with valid_invoices (default: {default_export})",
    )
    ap.add_argument("--delay", type=float, default=None, help="Seconds between submissions.")
    ap.add_argument("--max-retries", type=int, default=None, help="Retries per invoice.")
    args = ap.parse_args()

    from .service import submit_from_export

    report = submit_from_export(
        args.export,
        delay_between=args.delay,
        max_retries=args.max_retries,
    )
    if report.errors and report.attempted == 0:
        sys.exit(1)
    sys.exit(0 if report.failed == 0 else 2)


if __name__ == "__main__":
    main()
