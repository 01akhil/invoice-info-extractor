"""Poll the DB until jobs reach a terminal status."""

from receipt_pipeline.workers.orchestration.terminal_jobs.wait_for_terminal_jobs import wait_for_terminal_jobs

__all__ = ["wait_for_terminal_jobs"]
