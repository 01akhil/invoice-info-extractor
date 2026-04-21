import re
from datetime import datetime

from receipt_pipeline.ocr.utils import clean_text, bbox_to_rect, get_center

# Prefer ``Date: 25/03/2018`` on one visual line (OCR splits "Date" and value across tokens).
DATE_LABEL_PATTERN = re.compile(
    r"(?i)\b(?:invoice\s*)?date\b\s*[:#.\s-]{0,6}(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
)
# Some scans put the date *before* the word ``Date`` on the same line.
DATE_BEFORE_LABEL_PATTERN = re.compile(
    r"(?i)(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+\bdate\b",
)


# -------------------- Date Patterns --------------------
DATE_PATTERNS = [
    r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',        # 25/12/2018, 25-12-18
    r'\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b',          # 2018/12/25
    r'\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}\b',    # 25 Dec 2018
    r'\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4}\b'   # Dec 25, 2018
]

# -------------------- Normalize Date --------------------
def normalize_date(date_str):
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y",
        "%Y/%m/%d", "%Y-%m-%d",
        "%d %b %Y", "%d %B %Y",
        "%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y"
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.replace(",", ""), fmt)
            return dt.strftime("%d/%m/%Y")
        except:
            continue

    return date_str  # fallback


def _ocr_results_to_lines(results, y_tol: int = 14) -> list[list[tuple]]:
    """Group OCR tokens into horizontal lines by center-y."""
    if not results:
        return []
    ordered = sorted(results, key=lambda r: (get_center(r[2])[1], get_center(r[2])[0]))
    lines: list[list[tuple]] = []
    cur = [ordered[0]]
    last_cy = get_center(ordered[0][2])[1]
    for r in ordered[1:]:
        cy = get_center(r[2])[1]
        if abs(cy - last_cy) <= y_tol:
            cur.append(r)
        else:
            lines.append(cur)
            cur = [r]
            last_cy = cy
    lines.append(cur)
    return lines


def _bbox_for_date_token(line: list[tuple], raw_date: str) -> object:
    date_bbox = line[0][2]
    day_prefix = raw_date.strip().split("/")[0].split("-")[0]
    for _c, t, bb in line:
        if day_prefix and day_prefix in t.replace(" ", ""):
            date_bbox = bb
            break
    return date_bbox


def _extract_date_from_date_label_line(results) -> dict | None:
    """If a line contains ``Date`` and a DD/MM/YYYY, use that (beats stray dates elsewhere)."""
    for line in _ocr_results_to_lines(results):
        line_text = " ".join(clean_text(t) for _c, t, _b in line)
        m = DATE_LABEL_PATTERN.search(line_text)
        if not m:
            m = DATE_BEFORE_LABEL_PATTERN.search(line_text)
        if not m:
            continue
        raw = m.group(1)
        if ":" in raw:
            continue
        norm_date = normalize_date(raw)
        date_bbox = _bbox_for_date_token(line, raw)
        confs: list[float] = []
        for c, _, __ in line:
            try:
                confs.append(float(c) if c is not None else 0.5)
            except (TypeError, ValueError):
                confs.append(0.5)
        avg_c = sum(confs) / len(confs) if confs else 0.5
        return {
            "date": norm_date,
            "bbox": date_bbox,
            "text": norm_date,
            "score": 1_000_000.0,
            "confidence": avg_c,
        }
    return None


def _extract_date_from_preprocessed_image(path: str) -> dict | None:
    """
    Use the same binarized resize as ``total_extractor`` — raw full-image OCR often
    misorders ``Date`` vs digits; preprocessed words match human-readable receipts better.
    """
    from receipt_pipeline.extractors.total_extractor import get_words, group_rows

    rows = group_rows(get_words(path))
    for row in rows:
        line_text = " ".join(w["text"] for w in row)
        m = DATE_LABEL_PATTERN.search(line_text)
        if not m:
            m = DATE_BEFORE_LABEL_PATTERN.search(line_text)
        if not m:
            continue
        raw = m.group(1)
        if ":" in raw:
            continue
        norm_date = normalize_date(raw)
        date_bbox = (row[0]["x"], row[0]["y"], row[0]["w"], row[0]["h"])
        for w in row:
            if raw.split("/")[0].split("-")[0] in w["text"].replace(" ", ""):
                date_bbox = (w["x"], w["y"], w["w"], w["h"])
                break
        return {
            "date": norm_date,
            "bbox": date_bbox,
            "text": norm_date,
            "score": 1_000_001.0,
            "confidence": 0.93,
        }
    return None


# -------------------- Main Extraction --------------------
def extract_invoice_date(results, image_path: str | None = None):
    """results items are (confidence, text, bbox) as produced by ``OCRReader.read``."""
    if image_path:
        pre = _extract_date_from_preprocessed_image(image_path)
        if pre:
            return {
                "date": pre["date"],
                "bbox": bbox_to_rect(pre["bbox"]),
                "text": pre["date"],
                "score": pre["score"],
                "confidence": pre["confidence"],
            }

    preferred = _extract_date_from_date_label_line(results)
    if preferred:
        return {
            "date": preferred["date"],
            "bbox": bbox_to_rect(preferred["bbox"]),
            "text": preferred["date"],
            "score": preferred["score"],
            "confidence": preferred["confidence"],
        }

    candidates = []

    for conf, text, bbox in results:
        text_clean = clean_text(text)
        text_lower = text_clean.lower()

        for pattern in DATE_PATTERNS:
            matches = re.findall(pattern, text_clean)
            for match in matches:

                # Skip time-like values
                if ":" in match:
                    continue

                norm_date = normalize_date(match)

                try:
                    confidence = float(conf) if conf is not None else 1.0
                except (TypeError, ValueError):
                    confidence = 0.0

                _cx, cy = get_center(bbox)

                # SCORING
                score = 0

                #   keyword boost
                if "date" in text_lower:
                    score += 50

                if "invoice" in text_lower:
                    score += 20

                # top preference (invoice date is usually upper half; demote footer GST lines)
                score += max(0, 120 - cy * 0.55)

                #   confidence boost
                score += confidence * 20

                candidates.append({
                    "date": norm_date,
                    "bbox": bbox,
                    "score": score,
                    "confidence": confidence,
                    "raw_text": text_clean
                })

    #  No candidate
    if not candidates:
        return None

    # pick best
    best = max(candidates, key=lambda x: x["score"])

    return {
        "date": best["date"],
        "bbox": bbox_to_rect(best["bbox"]),
        "text": best["date"],
        "score": best["score"],
        "confidence": best["confidence"]
    }



