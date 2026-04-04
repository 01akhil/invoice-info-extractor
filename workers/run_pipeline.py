"""CLI shim: ``python -m workers.run_pipeline`` (long-running workers only)."""

from __future__ import annotations

import multiprocessing

from workers.pipelines.run_pipeline import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
