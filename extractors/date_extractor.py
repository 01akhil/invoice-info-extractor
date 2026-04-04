

import re
from datetime import datetime
from ocr.utils import clean_text, bbox_to_rect, get_center

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


# -------------------- Main Extraction --------------------
def extract_invoice_date(results):
    """results items are (confidence, text, bbox) as produced by ``OCRReader.read``."""
    candidates = []

    for conf, text, bbox in results:
        text_clean = clean_text(text)
        text_lower = text_clean.lower()

        for pattern in DATE_PATTERNS:
            matches = re.findall(pattern, text_clean)
            for match in matches:

                # ❌ Skip time-like values
                if ":" in match:
                    continue

                norm_date = normalize_date(match)

                try:
                    confidence = float(conf) if conf is not None else 1.0
                except (TypeError, ValueError):
                    confidence = 0.0

                _cx, cy = get_center(bbox)

                # 🔥 SCORING
                score = 0

                # ✅ keyword boost
                if "date" in text_lower:
                    score += 50

                if "invoice" in text_lower:
                    score += 20

                # ✅ top preference (dates usually top)
                score += max(0, 100 - cy * 0.5)

                # ✅ confidence boost
                score += confidence * 20

                candidates.append({
                    "date": norm_date,
                    "bbox": bbox,
                    "score": score,
                    "confidence": confidence,
                    "raw_text": text_clean
                })

    # ❗ No candidate
    if not candidates:
        return None

    # ✅ pick best
    best = max(candidates, key=lambda x: x["score"])

    return {
        "date": best["date"],
        "bbox": bbox_to_rect(best["bbox"]),
        "text": best["date"],
        "score": best["score"],
        "confidence": best["confidence"]
    }



