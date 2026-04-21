"""Scan a folder for images and ingest each as a pipeline job."""

from __future__ import annotations

from pathlib import Path

import redis

from receipt_pipeline.workers.orchestration.ingestion.ingest_image import ingest_image
from receipt_pipeline.workers.utils.pipeline_log import pl_info, pl_warning


def ingest_folder(r: redis.Redis, folder: Path) -> list[str]:
    # Only consider common image file extensions
    exts = {".jpg", ".jpeg", ".png"}
    if not folder.is_dir():
        pl_warning("ingest", "folder_missing_or_not_a_directory", path=str(folder))
        return []
    ids: list[str] = []
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() in exts:
            ids.append(ingest_image(r, str(p)))
    pl_info("ingest", "folder_scan_done", folder=str(folder), jobs_enqueued=len(ids))
    return ids
