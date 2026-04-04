"""
Invoice validation package.

Public API matches the former monolithic module for backward compatibility.
"""

from __future__ import annotations

from typing import Any

from .gemini_extraction import GeminiInvoiceFieldExtractor
from schemas.models import InvoiceValidation
from .ocr import TesseractInvoiceOcr
from .pipeline import InvoiceValidationPipeline
from .prompts import GEMINI_PROMPT

__all__ = [
    "GEMINI_PROMPT",
    "GeminiInvoiceFieldExtractor",
    "InvoiceValidation",
    "InvoiceValidationPipeline",
    "TesseractInvoiceOcr",
    "extract_invoice_fields_llm",
    "perform_ocr",
    "validate_invoices",
]

_default_pipeline: InvoiceValidationPipeline | None = None
_default_ocr: TesseractInvoiceOcr | None = None
_default_extractor: GeminiInvoiceFieldExtractor | None = None


def _get_default_ocr() -> TesseractInvoiceOcr:
    global _default_ocr
    if _default_ocr is None:
        _default_ocr = TesseractInvoiceOcr()
    return _default_ocr


def _get_default_extractor() -> GeminiInvoiceFieldExtractor:
    global _default_extractor
    if _default_extractor is None:
        _default_extractor = GeminiInvoiceFieldExtractor()
    return _default_extractor


def _get_default_pipeline() -> InvoiceValidationPipeline:
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = InvoiceValidationPipeline(
            _get_default_ocr(),
            _get_default_extractor(),
        )
    return _default_pipeline


def validate_invoices(invoice_items: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """
    Validates invoices. LLM is called ONLY if direct validation fails.
    Returns valid_results and human_review lists.
    """
    return _get_default_pipeline().validate_batch(invoice_items)


def perform_ocr(file_path: str) -> str:
    """Preprocess image and extract text using Tesseract (default reader)."""
    return _get_default_ocr().read_text(file_path)


def extract_invoice_fields_llm(ocr_text: str) -> dict:
    """Use Gemini to extract vendor, date, total from OCR text (default extractor)."""
    return _get_default_extractor().extract_fields(ocr_text)
