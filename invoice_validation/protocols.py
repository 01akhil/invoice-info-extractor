"""Contracts for OCR and field extraction — enables swapping implementations (DIP)."""

from __future__ import annotations

from typing import Any, Protocol


class OcrReader(Protocol):
    """Single responsibility: turn an image file into raw OCR text."""

    def read_text(self, file_path: str) -> str:
        """Return extracted text, or empty string if unreadable."""
        ...


class InvoiceFieldExtractor(Protocol):
    """Single responsibility: map OCR text to structured invoice fields."""

    def extract_fields(self, ocr_text: str) -> dict[str, Any]:
        """Return a dict with keys vendor, date, total (values may be None)."""
        ...
