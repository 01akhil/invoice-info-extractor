"""CLI shim: ``python -m receipt_pipeline.workers.run_pipeline`` (workers only, no orchestrator)."""

from __future__ import annotations

import multiprocessing

from receipt_pipeline.workers.orchestration.run_pipeline import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
