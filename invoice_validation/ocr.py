"""Tesseract-based OCR — one implementation of OcrReader (OCP)."""

from __future__ import annotations

import os

import cv2
import pytesseract

from config.settings import TESSERACT_CMD

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


class TesseractInvoiceOcr:
    """Extract text from invoice images using OpenCV preprocessing + Tesseract."""

    def read_text(self, file_path: str) -> str:
        if not os.path.exists(file_path):
            print(f"  ⚠ File not found: {file_path}")
            return ""

        img = cv2.imread(file_path)
        if img is None:
            print(f"  ⚠ Could not read image: {file_path}")
            return ""

        h, w = img.shape[:2]
        if w < 800:
            scale = 800 / w
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        processed = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
        )

        text = pytesseract.image_to_string(processed, config="--oem 3 --psm 6")
        print(f"  📄 OCR extracted {len(text.split())} words from {file_path}")
        return text.strip()
