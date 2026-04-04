"""
Generate simple synthetic receipt PNGs (OpenCV text) for pipeline evaluation.
Requires: opencv-python, numpy (same as main project).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


def _make_one(out_path: Path, idx: int) -> None:
    vendors = [
        "Corner Market",
        "City Cafe",
        "Hardware Plus",
        "Quick Stop",
        "Fresh Foods Co",
        "Book Nook",
        "Gas & Go",
        "PharmaCare",
    ]
    vendor = vendors[idx % len(vendors)]
    day = 1 + (idx % 28)
    month = 1 + (idx % 12)
    year = 2024 + (idx % 2)
    date_str = f"{year}-{month:02d}-{day:02d}"
    total = round(12.5 + (idx * 7.37) % 500, 2)

    img = np.ones((900, 700, 3), dtype=np.uint8) * 255
    lines = [
        f"RECEIPT #{idx:04d}",
        "",
        f"Store: {vendor}",
        f"Date: {date_str}",
        f"Subtotal: ${total - 2:.2f}",
        f"Tax: $2.00",
        f"TOTAL DUE: ${total:.2f}",
        "",
        "Thank you",
    ]
    y = 50
    for line in lines:
        cv2.putText(
            img,
            line,
            (40, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (15, 15, 15),
            2,
            cv2.LINE_AA,
        )
        y += 42

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), img)


def main() -> None:
    p = argparse.ArgumentParser(description="Generate synthetic receipt PNGs for evaluation.")
    p.add_argument("out_dir", type=Path, help="Output directory")
    p.add_argument("count", type=int, nargs="?", default=24, help="Number of receipts (default 24)")
    args = p.parse_args()
    n = max(1, args.count)
    for i in range(n):
        _make_one(args.out_dir / f"eval_receipt_{i:04d}.png", i)
    print(f"Wrote {n} PNG(s) to {args.out_dir.resolve()}", file=sys.stderr)


if __name__ == "__main__":
    main()
