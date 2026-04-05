"""CLI: ingest all images from IMAGES_DIR into the pipeline (requires Redis + running workers)."""

from __future__ import annotations

import argparse
from pathlib import Path

from config.settings import IMAGES_DIR
from config.logger_setup import get_logger
from receipt_pipeline.workers.db.session import init_db
from receipt_pipeline.workers.orchestration.ingestion import ingest_folder
from receipt_pipeline.workers.redis.redis_client import get_redis

logger = get_logger()


def main() -> None:
    from receipt_pipeline.workers.redis.redis_health import ensure_redis

    parser = argparse.ArgumentParser(description="Enqueue invoice images for OCR processing.")
    parser.add_argument(
        "--folder",
        type=str,
        default=str(IMAGES_DIR),
        help="Folder containing invoice images (default: config IMAGES_DIR)",
    )
    args = parser.parse_args()
    ensure_redis()
    init_db()
    r = get_redis()
    ids = ingest_folder(r, Path(args.folder))
    logger.info("Ingested %s job(s).", len(ids))


if __name__ == "__main__":
    main()
