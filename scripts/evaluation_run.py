"""
Evaluation helper: optional clean DB/Redis, then runs ``main.py`` (pipeline only).

  python scripts/evaluation_run.py [--images-dir PATH]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RESULTS = ROOT / "results"
EXPORT_JSON = RESULTS / "pipeline_export.json"
DEFAULT_IMAGES = ROOT / "images"

_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def _list_ingest_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTS)


def _fresh_db() -> None:
    db = ROOT / "data" / "invoices.db"
    if db.is_file():
        db.unlink()
        print("Removed old DB", file=sys.stderr)


def _flush_redis() -> None:
    try:
        subprocess.run(
            ["redis-cli", "FLUSHALL"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        print("Redis cleared", file=sys.stderr)
    except Exception:
        print("Warning: Redis not cleared", file=sys.stderr)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Run pipeline with optional clean state, then print outcomes.")
    ap.add_argument("--images-dir", type=Path, default=None, help="Image folder (top-level jpg/png only)")
    args = ap.parse_args()

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))

    from pipeline.evaluation_summary import write_summary_from_export

    _flush_redis()
    _fresh_db()

    images_root = (args.images_dir or DEFAULT_IMAGES).resolve()
    os.environ["IMAGES_DIR"] = str(images_root)

    discovered = _list_ingest_images(images_root)
    if not discovered:
        print(f"No images found in {images_root}", file=sys.stderr)
        sys.exit(2)

    print(f"Evaluating {len(discovered)} images from {images_root}", file=sys.stderr)
    RESULTS.mkdir(parents=True, exist_ok=True)

    r = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--pipeline-timeout", "1200"],
        env={**os.environ},
    )
    if r.returncode != 0:
        print("Pipeline failed", file=sys.stderr)
        sys.exit(r.returncode)

    if not EXPORT_JSON.is_file():
        print("No pipeline_export.json found", file=sys.stderr)
        sys.exit(2)

    summary_path = RESULTS / "evaluation_summary.json"
    if summary_path.is_file():
        analysis = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        data = json.loads(EXPORT_JSON.read_text(encoding="utf-8"))
        analysis = write_summary_from_export(data, images_dir=str(images_root))
    print("\n===== OUTCOMES =====")
    print(json.dumps(analysis["outcomes"], indent=2))


if __name__ == "__main__":
    main()
