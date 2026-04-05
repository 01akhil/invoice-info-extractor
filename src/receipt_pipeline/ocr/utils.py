"""Shared helpers for OCR pipelines (text normalization, geometry)."""

from __future__ import annotations

import re
from typing import Any


def clean_text(text: str | None) -> str:
    """Normalize whitespace; empty input becomes empty string."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_center(bbox: Any) -> tuple[float, float]:
    """Center (x, y) for Tesseract (x, y, w, h) or EasyOCR four-point boxes."""
    if isinstance(bbox, (tuple, list)):
        if len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
            x, y, w, h = bbox
            return x + w / 2, y + h / 2
        if len(bbox) == 4 and all(isinstance(v, (list, tuple)) for v in bbox):
            x_vals = [p[0] for p in bbox]
            y_vals = [p[1] for p in bbox]
            return (min(x_vals) + max(x_vals)) / 2, (min(y_vals) + max(y_vals)) / 2
    return 0.0, 0.0


def bbox_to_rect(bbox: Any) -> tuple[int, int, int, int] | None:
    """Convert a bbox to (x, y, w, h) for drawing with OpenCV."""
    if isinstance(bbox, (tuple, list)):
        if len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
            return tuple(int(v) for v in bbox)
        if len(bbox) == 4 and all(isinstance(v, (list, tuple)) for v in bbox):
            x_vals = [p[0] for p in bbox]
            y_vals = [p[1] for p in bbox]
            x, y = min(x_vals), min(y_vals)
            w, h = max(x_vals) - x, max(y_vals) - y
            return int(x), int(y), int(w), int(h)
    return None
