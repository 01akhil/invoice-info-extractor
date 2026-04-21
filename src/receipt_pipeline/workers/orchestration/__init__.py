"""
Pipeline orchestration: grouped by concern.

- ``ingestion`` — enqueue images (DB + Redis OCR queue)
- ``export`` — JSON/CSV export
- ``terminal_jobs`` — wait until jobs finish in the DB
- ``worker_startup`` — spawn worker processes/threads
- ``orchestrator`` — one-shot ``run_pipeline`` wiring the phases
"""
