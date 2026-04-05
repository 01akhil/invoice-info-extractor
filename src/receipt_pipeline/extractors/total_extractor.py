"""Receipt total extraction via Tesseract word boxes and label scoring."""

import re

import cv2
import pytesseract

from config.settings import TESSERACT_CMD

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# ─────────────────────────────────────────────────────────
# CONFIGURATION & LABELS
# ─────────────────────────────────────────────────────────

TOTAL_LABELS = [
    (r"total\s*payable", 4000),
    (r"net\s*payable", 3950),
    (r"amount\s*payable", 3900),
    (r"amount\s*due", 3850),
    (r"balance\s*due", 3800),
    (r"rounded\s*total\s*\(?rm\)?", 3200),
    (r"total\s*rounded", 3100),
    (r"grand\s*total", 3100),
    (r"total\s*sales\s*[\(\[]?inclu", 2900),
    (r"amount\s*payable", 2700),
    (r"total\s*amount", 2500),
    (r"total\s*sales", 2400),
    (r"total\s*amt", 2300),
    (r"total\s*gross", 2200),
    (r"\btotal\b", 2000),
]

SKIP_LABELS = [
    r"\bdiscount\b",
    r"rounding",
    r"total\s*gst",
    r"sub.?total",
    r"tax",
    r"paid",
    r"total\s*qty",
    r"total\s*item",
    r"change",
    r"cash",
    r"tendered",
]


def preprocess(path):
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)
    h, w = img.shape[:2]
    if w < 800:
        img = cv2.resize(img, None, fx=800 / w, fy=800 / w)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        10,
    )


def get_words(path):
    img = preprocess(path)
    data = pytesseract.image_to_data(
        img, config="--oem 3 --psm 6", output_type=pytesseract.Output.DICT
    )
    words = []
    for i in range(len(data["text"])):
        t = data["text"][i].strip()
        if not t or int(data["conf"][i]) < 10:
            continue
        words.append(
            {
                "text": t,
                "x": data["left"][i],
                "y": data["top"][i],
                "w": data["width"][i],
                "h": data["height"][i],
                "cx": data["left"][i] + data["width"][i] // 2,
                "cy": data["top"][i] + data["height"][i] // 2,
                "x2": data["left"][i] + data["width"][i],
            }
        )
    return words


def group_rows(words, y_tol=14):
    if not words:
        return []
    words = sorted(words, key=lambda w: w["cy"])
    rows, cur = [], [words[0]]
    for w in words[1:]:
        if abs(w["cy"] - cur[-1]["cy"]) <= y_tol:
            cur.append(w)
        else:
            rows.append(sorted(cur, key=lambda w: w["x"]))
            cur = [w]
    rows.append(sorted(cur, key=lambda w: w["x"]))
    return rows


def parse_amount(text):
    t = text.lower().strip()
    t = re.sub(r"(?i)^rm", "", t)
    t = t.replace("o", "0").replace(",", ".")
    t = re.sub(r"[^\d.]", "", t)
    if not re.fullmatch(r"\d+(\.\d{1,2})?", t):
        return None
    try:
        v = float(t)
        return v if v >= 1 else None
    except ValueError:
        return None


def score_label(text):
    t = text.lower()
    if any(re.search(skip, t) for skip in SKIP_LABELS):
        return 0
    for pattern, score in TOTAL_LABELS:
        if re.search(pattern, t):
            return score
    return 0


def extract_total(path):
    words = get_words(path)
    if not words:
        return None, 0.0, None

    rows = group_rows(words)
    candidates = []

    for i, row in enumerate(rows):
        rt = " ".join(w["text"] for w in row)
        label_score = score_label(rt)
        if label_score == 0:
            continue

        row_amounts = []
        for w in row:
            val = parse_amount(w["text"])
            if val is not None:
                row_amounts.append(
                    {"val": val, "bbox": (w["x"], w["y"], w["w"], w["h"])}
                )

        if not row_amounts:
            continue

        best_amount = max(row_amounts, key=lambda x: x["val"])

        candidates.append(
            {
                "val": best_amount["val"],
                "score": label_score - (i * 5),
                "bbox": best_amount["bbox"],
            }
        )

    if not candidates:
        return None, 0.0, None

    candidates.sort(key=lambda x: x["score"], reverse=True)
    best = candidates[0]

    confidence = min(1.0, best["score"] / 3200)
    return best["val"], confidence, best["bbox"]
