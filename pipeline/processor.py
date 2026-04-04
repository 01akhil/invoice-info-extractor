

from extractors.total_extractor import extract_total
from extractors.date_extractor import extract_invoice_date
from extractors.vendor_extractor import extract_vendor
from pipeline.fallback import apply_llm_fallback


def _to_xywh(bbox):
    """Normalize any bbox format to (x, y, w, h) int tuple."""
    if bbox is None:
        return None
    # Already a flat 4-tuple: (x, y, w, h)
    if isinstance(bbox, (tuple, list)) and len(bbox) == 4 and not isinstance(bbox[0], (list, tuple)):
        return tuple(map(int, bbox))
    # List of points: [[x1,y1],[x2,y2],...]
    if isinstance(bbox, (tuple, list)) and isinstance(bbox[0], (list, tuple)):
        xs = [int(p[0]) for p in bbox]
        ys = [int(p[1]) for p in bbox]
        x, y = min(xs), min(ys)
        return x, y, max(xs) - x, max(ys) - y
    # Dict with x, y, w, h keys
    if isinstance(bbox, dict):
        return int(bbox['x']), int(bbox['y']), int(bbox['w']), int(bbox['h'])
    return None


def process_single_invoice(path, ocr_engine):
    """Extracts data from one image and handles the LLM fallback logic."""
    image, ocr_results = ocr_engine.read(path)

    # 1. Primary Extraction
    total_val, total_conf, total_bbox = extract_total(path)

    date_data = extract_invoice_date(ocr_results)
    date_val = date_data["date"] if date_data else None
    date_bbox = date_data["bbox"] if date_data else None
    date_conf = date_data["confidence"] if date_data else 0.0

    vendor_name, vendor_conf, vendor_bbox = extract_vendor(path)

    # Normalize all bboxes to (x, y, w, h) right here
    total_bbox  = _to_xywh(total_bbox)
    date_bbox   = _to_xywh(date_bbox)
    vendor_bbox = _to_xywh(vendor_bbox)

    # 2. LLM Fallback
    vendor_name, total_val, date_val, triggered, llm_parsed = apply_llm_fallback(
        vendor_name, vendor_conf,
        total_val, total_conf,
        date_val, date_conf,
        ocr_results
    )

    # 3. Construct Result Object
    if triggered:
        result = {
            "file": path,
            "vendor": llm_parsed.get("vendor"),
            "total": llm_parsed.get("total"),
            "date": llm_parsed.get("date"),
            "llm_used": True
        }
    else:
        result = {
            "file": path,
            "vendor": vendor_name,
            "total": total_val,
            "date": date_val,
            "vendor_conf": vendor_conf,
            "total_conf": total_conf,
            "date_conf": date_conf,
            "llm_used": False
        }

    return result, image, triggered, (total_bbox, date_bbox, vendor_bbox)