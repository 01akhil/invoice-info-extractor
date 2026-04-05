# Workers (`receipt_pipeline.workers`)

Long-running processes for the Redis-backed invoice pipeline.

| Area | Role |
|------|------|
| `core/` | OCR (multiprocess), post-OCR, LLM pool, validation loops |
| `db/` | SQLAlchemy models, session (SQLite WAL), CRUD |
| `orchestration/` | Ingest folder → queues, wait for jobs, export JSON/CSV, orchestrator |
| `redis/` | Client and connectivity checks |
| `retry/` | Retry ZSET scheduler and backoff policy |
| `utils/` | Redis metrics, structured pipeline logs, circuit breaker |
| `human_review_store.py` | Persists `results/human_review_queue.json` |
| `config.py` | Re-exports root `config.settings` (queues, worker counts, timeouts) |

The app entrypoint is [`main.py`](../../../main.py) at the repository root (full pipeline or `--submit-only`).
