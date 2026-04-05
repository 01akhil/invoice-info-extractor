"""
Pipeline stages for queue-based processing: OCR snapshot serialization, rule extraction, routing.
"""

from __future__ import annotations

from typing import Any

from receipt_pipeline.extractors.date_extractor import extract_invoice_date
from receipt_pipeline.extractors.total_extractor import extract_total
from receipt_pipeline.extractors.vendor_extractor import extract_vendor


def _to_xywh(bbox):
    """Normalize any bbox format to (x, y, w, h) int tuple."""
    if bbox is None:
        return None
    if isinstance(bbox, (tuple, list)) and len(bbox) == 4 and not isinstance(bbox[0], (list, tuple)):
        return tuple(map(int, bbox))
    if isinstance(bbox, (tuple, list)) and bbox and isinstance(bbox[0], (list, tuple)):
        xs = [int(p[0]) for p in bbox]
        ys = [int(p[1]) for p in bbox]
        x, y = min(xs), min(ys)
        return x, y, max(xs) - x, max(ys) - y
    if isinstance(bbox, dict):
        return int(bbox["x"]), int(bbox["y"]), int(bbox["w"]), int(bbox["h"])
    return None


def aggregate_ocr_confidence(ocr_results: list) -> float:
    confs: list[float] = []
    for res in ocr_results:
        if isinstance(res, (list, tuple)) and len(res) >= 1:
            try:
                confs.append(float(res[0]))
            except (TypeError, ValueError):
                continue
    if not confs:
        return 0.0
    return sum(confs) / len(confs)


def ocr_results_to_serializable(ocr_results: list) -> list:
    """Serialize OCR tuples for JSON/SQLite storage."""
    out = []
    for res in ocr_results:
        if isinstance(res, (list, tuple)) and len(res) >= 3:
            conf, text, bbox = res[0], res[1], res[2]
            bb = list(bbox) if hasattr(bbox, "__iter__") and not isinstance(bbox, str) else bbox
            out.append({"conf": float(conf), "text": text, "bbox": bb})
    return out


def serializable_to_ocr_results(data: list | None) -> list:
    """Restore OCR structure expected by extract_invoice_date / fallback."""
    if not data:
        return []
    out = []
    for item in data:
        if isinstance(item, dict):
            conf = item.get("conf", 0.0)
            text = item.get("text", "")
            bbox = item.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                bbox = tuple(bbox)
            out.append((float(conf), text, bbox))
    return out


def run_rule_extraction(path: str, ocr_results: list) -> dict[str, Any]:
    """
    Fast path: regex/heuristic extractors only (no LLM).
    Regex/heuristic extractors only; bbox normalization via `_to_xywh`.
    """
    total_val, total_conf, total_bbox = extract_total(path)
    date_data = extract_invoice_date(ocr_results)
    date_val = date_data["date"] if date_data else None
    date_bbox = date_data["bbox"] if date_data else None
    date_conf = date_data["confidence"] if date_data else 0.0
    vendor_name, vendor_conf, vendor_bbox = extract_vendor(path)

    total_bbox = _to_xywh(total_bbox)
    date_bbox = _to_xywh(date_bbox)
    vendor_bbox = _to_xywh(vendor_bbox)

    return {
        "file": path,
        "vendor": vendor_name,
        "total": total_val,
        "date": date_val,
        "vendor_conf": float(vendor_conf) if vendor_conf is not None else 0.0,
        "total_conf": float(total_conf) if total_conf is not None else 0.0,
        "date_conf": float(date_conf) if date_conf is not None else 0.0,
        "bboxes": (total_bbox, date_bbox, vendor_bbox),
    }


def should_route_to_llm(vendor_conf: float, total_conf: float, date_conf: float) -> bool:
    """Same thresholds as `apply_llm_fallback` (confidence-based routing)."""
    return (vendor_conf < 0.5) or (total_conf < 0.05) or (date_conf < 0.1)


def build_extraction_payload(rule: dict, source: str, llm_used: bool) -> dict:
    """Flatten rule output + metadata for validation / DB."""
    confs = [rule["vendor_conf"], rule["total_conf"], rule["date_conf"]]
    confidence = sum(confs) / max(len(confs), 1)
    return {
        "file": rule["file"],
        "vendor": rule["vendor"],
        "total": rule["total"],
        "date": rule["date"],
        "vendor_conf": rule["vendor_conf"],
        "total_conf": rule["total_conf"],
        "date_conf": rule["date_conf"],
        "confidence": confidence,
        "source": source,
        "llm_used": llm_used,
    }


def extraction_payload_from_llm_parsed(
    file_path: str,
    parsed: dict,
    llm_used: bool = True,
) -> dict:
    """Build payload after LLM parse (confidence unknown → use 0.85 default)."""
    return {
        "file": file_path,
        "vendor": parsed.get("vendor"),
        "total": parsed.get("total"),
        "date": parsed.get("date"),
        "vendor_conf": 0.85,
        "total_conf": 0.85,
        "date_conf": 0.85,
        "confidence": 0.85,
        "source": "LLM",
        "llm_used": llm_used,
    }
