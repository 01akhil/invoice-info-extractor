# Workers (`receipt_pipeline.workers`)

Long-running processes for the Redis-backed invoice pipeline.

Shared infrastructure (not worker-specific) lives next to this package:

| Package | Role |
|---------|------|
| [`receipt_pipeline.db`](../db/) | SQLAlchemy models, session (SQLite WAL), CRUD, query retry helper |
| [`receipt_pipeline.redis_queue`](../redis_queue/) | Redis client and startup connectivity check |

| Area | Role |
|------|------|
| `core/` | OCR (multiprocess), post-OCR, LLM pool, validation loops |
| `orchestration/` | `orchestrator` (one-shot run); subfolders: `ingestion/`, `export/`, `terminal_jobs/`, `worker_startup/` |
| `retry/` | Retry ZSET scheduler and backoff policy |
| `utils/` | Redis metrics, structured pipeline logs, circuit breaker |
| `human_review_store.py` | Persists `results/human_review_queue.json` |
| `config.py` | Re-exports root `config.settings` (queues, worker counts, timeouts) |

The app entrypoint is [`main.py`](../../../main.py) at the repository root (full pipeline or `--submit-only`).
