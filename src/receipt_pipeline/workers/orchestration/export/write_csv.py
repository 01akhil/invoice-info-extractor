"""Write a list of flat dict rows to CSV."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def write_flat_dict_rows_csv(path: Path, flat_rows: list[dict[str, Any]]) -> None:
    if not flat_rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(flat_rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(flat_rows)
