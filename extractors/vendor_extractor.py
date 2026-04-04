import re
import unicodedata

import cv2
import pytesseract

from config.settings import TESSERACT_CMD

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

TOP_PORTION = 0.21
CONF_THRESHOLD = 45       # lowered: some receipts have globally lower OCR conf
MAX_LINES = 8            # FIX 2: was 6; handwritten header eats top lines

# FIX 3: use whole-word / phrase matching only — no bare substrings like "no"
# Keep these as complete tokens to avoid substring false-positives
NEGATIVE_PHRASES = [
    "tax invoice", "simplified tax invoice", "invoice", "receipt",
    "cash bill", "cash sales",
    "tel:", "fax:", "gst", "reg no", "co.reg",
    "date", "time", "cashier", "salesperson", "member",
    "thank you", "welcome", "change:", "cash:", "amount",
    "jalan", "jln", "road", "street", "lane", "drive",
    "taman", "tmn", "bandar", "lot ", "block",
    "johor", "selangor", "kuala lumpur", "shah alam",
    "seri kembangan", "petaling jaya",
    "tan woon yann", "tan chay yee",   # customer names in this dataset
]

POSITIVE_WORDS = [
    "enterprise", "trading", "store", "mart", "supermarket",
    "restaurant", "restoran", "cafe", "bakery", "coffee", "shop",
    "sdn bhd", "sdn. bhd", "bhd", "ltd", "limited", "co.",
    "hardware", "machinery", "motor", "perniagaan", "gift", "deco",
]


# ─── helpers ──────────────────────────────────────────────────────────────────

def normalize(text):
    return unicodedata.normalize("NFKC", text).strip()

def clean_line(text):
    # keep letters, spaces, & . ' - ( )
    return re.sub(r"[^A-Za-z\s&.\'\-()]", "", text).strip()

def has_digits(text):
    return bool(re.search(r"\d", text))

def uppercase_ratio(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(c.isupper() for c in letters) / len(letters)

def positive_score(text):
    t = text.lower()
    return sum(1 for w in POSITIVE_WORDS if w in t)

def is_bad_line(text):
    t = text.lower()
    if len(text) < 3:
        return True
    # FIX 3: check phrase membership, not bare substring on raw tokens like "no"
    if any(phrase in t for phrase in NEGATIVE_PHRASES):
        return True
    if has_digits(text):
        return True
    return False

def merge_bbox(bboxes):
    x_min = min(b[0] for b in bboxes)
    y_min = min(b[1] for b in bboxes)
    x_max = max(b[0] + b[2] for b in bboxes)
    y_max = max(b[1] + b[3] for b in bboxes)
    return (x_min, y_min, x_max - x_min, y_max - y_min)

def is_unreliable(conf_list, height_list):
    """Detect handwriting / stamps by OCR confidence and height variance."""
    if not conf_list:
        return True
    # FIX 4: Tesseract returns int -1, not string '-1'; filter properly
    valid = [c for c in conf_list if isinstance(c, int) and c >= 0]
    if not valid:
        return True
    avg_conf = sum(valid) / len(valid)
    if avg_conf < CONF_THRESHOLD:
        return True
    # FIX 5: raised variance multiplier from 0.8 → 1.5
    # Large printed capitals naturally vary in height vs. lowercase descenders
    if len(height_list) > 1:
        avg_h = sum(height_list) / len(height_list)
        if avg_h > 0 and (max(height_list) - min(height_list)) > avg_h * 1.5:
            return True
    return False


# ─── main ─────────────────────────────────────────────────────────────────────

def extract_vendor(image_path, draw=True):
    image = cv2.imread(image_path)
    if image is None:
        return None, 0.0, None

    h, w = image.shape[:2]
    top_img = image[:int(h * TOP_PORTION), :]

    # LSTM engine + auto page-seg for better accuracy
    cfg = r"--oem 3 --psm 6"
    ocr = pytesseract.image_to_data(top_img, config=cfg, output_type=pytesseract.Output.DICT)

    # ── group tokens into visual lines ────────────────────────────────────────
    lines, line_confs, line_heights, line_bboxes = [], [], [], []
    cur_txt, cur_conf, cur_h, cur_box = [], [], [], []
    last_y = -1

    for i, text in enumerate(ocr["text"]):
        text = text.strip()
        if not text:
            continue

        # FIX 4: conf is already an int from DICT output; guard against -1 int
        conf = ocr["conf"][i]
        conf = int(conf) if conf != -1 else -1

        x, y, bw, bh = ocr["left"][i], ocr["top"][i], ocr["width"][i], ocr["height"][i]

        # FIX 1: raised tolerance from 10 → 15px — same-line words can differ
        if last_y == -1 or abs(y - last_y) < 15:
            cur_txt.append(text); cur_conf.append(conf)
            cur_h.append(bh);     cur_box.append((x, y, bw, bh))
        else:
            lines.append(" ".join(cur_txt))
            line_confs.append(cur_conf[:]);   line_heights.append(cur_h[:])
            line_bboxes.append(merge_bbox(cur_box))
            cur_txt, cur_conf, cur_h, cur_box = [text], [conf], [bh], [(x, y, bw, bh)]

        last_y = y

    if cur_txt:
        lines.append(" ".join(cur_txt))
        line_confs.append(cur_conf); line_heights.append(cur_h)
        line_bboxes.append(merge_bbox(cur_box))

    # ── filter ────────────────────────────────────────────────────────────────
    clean_lines, clean_bboxes = [], []

    for i in range(min(len(lines), MAX_LINES)):      # FIX 2
        raw   = normalize(lines[i])
        clean = clean_line(raw)
        if not clean:
            continue
        if is_unreliable(line_confs[i], line_heights[i]):
            continue
        if is_bad_line(clean):
            continue
        clean_lines.append(clean)
        clean_bboxes.append(line_bboxes[i])

    if not clean_lines:
        return None, 0.0, None

    # ── score candidates ──────────────────────────────────────────────────────
    candidates = []

    for i in range(len(clean_lines)):
        for j in range(i, min(i + 3, len(clean_lines))):
            combined = " ".join(clean_lines[i : j + 1])
            bbox     = merge_bbox(clean_bboxes[i : j + 1])

            up  = uppercase_ratio(combined)
            pos = positive_score(combined)

            score = up * 120 + pos * 40

            # FIX 6: removed hard skip for pos==0 and up<0.6
            # Mixed-case names like "Restoran Hassanbistro" would be lost.
            # Use a softer penalty instead:
            if pos == 0 and up < 0.5:
                score -= 40          # penalise but don't discard

            # length sweet spot
            n = len(combined)
            if 5 < n < 45:
                score += 60
            elif n > 60:
                score -= 50

            # word-count penalty (addresses have many words)
            if combined.count(" ") > 5:
                score -= 30

            # position bonus — vendor name is near the top
            score += max(0, 50 - i * 10)
            if i < 2:
                score += 25

            candidates.append((score, combined, bbox))

    if not candidates:
        return None, 0.0, None

    candidates.sort(reverse=True)
    best_score, best_vendor, best_bbox = candidates[0]

    if best_score < 80:                 # lowered threshold to match new scoring
        return None, 0.0, None

    # FIX 7: normalize against realistic max score, not arbitrary 180
    max_possible = 120 + 40 + 60 + 50 + 25   # up*120 + pos*40 + len + pos_bonus + top_bonus
    confidence = round(min(1.0, best_score / max_possible), 3)

    # ── draw box ──────────────────────────────────────────────────────────────
    if draw:
        x, y, bw, bh = best_bbox
        cv2.rectangle(image, (x, y), (x + bw, y + bh), (0, 220, 80), 2)
        cv2.putText(image, best_vendor, (x, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 80), 1)
      

    return best_vendor, confidence, best_bbox