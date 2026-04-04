# Workers package

Long-running processes for the Redis-backed invoice pipeline.

| Area | Role |
|------|------|
| `core/` | OCR (multiprocess), post-OCR, LLM pool, validation loops |
| `db/` | SQLAlchemy models, session (SQLite WAL), CRUD |
| `pipelines/` | Ingest folder → queues, wait for jobs, export JSON/CSV |
| `redis/` | Client and connectivity checks |
| `retry/` | Retry ZSET scheduler and backoff policy |
| `utils/` | Redis metrics, structured pipeline logs, circuit breaker |
| `human_review_store.py` | Persists `results/human_review_queue.json` |
| `api.py` | Optional FastAPI surface for daemon mode |
| `config.py` | Re-exports `config.settings` (queues, worker counts, timeouts) |
| `run_pipeline.py` | Thin CLI shim: `python -m workers.run_pipeline` |

Orchestration (`start_workers`, ingest, export) lives under `workers/pipelines/`; the app entrypoint is `main.py` at the repo root.
