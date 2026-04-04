"""Gemini-based field extraction — one implementation of InvoiceFieldExtractor (OCP)."""

from __future__ import annotations

import json
import re
from typing import Any

from llm.client import get_generative_model

from .prompts import GEMINI_PROMPT


class GeminiInvoiceFieldExtractor:
    """Parse vendor, date, total from OCR text via Gemini."""

    def __init__(self, model=None):
        self._model = model if model is not None else get_generative_model()

    def extract_fields(self, ocr_text: str) -> dict[str, Any]:
        if not ocr_text.strip():
            return {"vendor": None, "date": None, "total": None}

        try:
            prompt = GEMINI_PROMPT.format(ocr_text=ocr_text[:3000])
            response = self._model.generate_content(prompt)
            raw = response.text.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            extracted = json.loads(raw)
            return {
                "vendor": extracted.get("vendor"),
                "date": extracted.get("date"),
                "total": extracted.get("total"),
            }
        except Exception as e:
            print(f"  ⚠ Gemini error: {e}")
            return {"vendor": None, "date": None, "total": None}
