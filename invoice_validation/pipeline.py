"""Orchestrates direct validation, OCR fallback, and human-review queue (SRP: workflow only)."""

from __future__ import annotations
from typing import Any
from pydantic import ValidationError
from schemas.models import InvoiceValidation
from .protocols import InvoiceFieldExtractor, OcrReader
from config.logger_setup import get_logger

logger=get_logger()

class InvoiceValidationPipeline:
    """
    Two-phase validation: trust structured input first; on failure, OCR + LLM + re-validate.
    Depends on OcrReader and InvoiceFieldExtractor abstractions (DIP).
    """

    def __init__(
        self,
        ocr_reader: OcrReader,
        field_extractor: InvoiceFieldExtractor,
    ) -> None:
        self._ocr = ocr_reader
        self._extractor = field_extractor

    def validate_batch(
        self, invoice_items: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        valid_results: list[dict[str, Any]] = []
        human_review: list[dict[str, Any]] = []
        
        logger.info("🚀 Validation started")
        logger.info(self.__doc__)

        for item in invoice_items:
            file_path = item.get("file")
            logger.info("🔹 Processing: %s", file_path)

            try:
                validated = InvoiceValidation(**item)
                valid_results.append(validated.model_dump(mode="json"))
                logger.info("  ✅ Validation PASSED: %s", validated.model_dump(mode='json'))
                continue
            except ValidationError:
                logger.warning("  ⚠ Validation FAILED, invoking LLM...")

            ocr_text = self._ocr.read_text(file_path)
            extracted = self._extractor.extract_fields(ocr_text)
            logger.info("  🤖 LLM extracted fields: %s", extracted)

            try:
                validated = InvoiceValidation(file=file_path, **extracted)
                valid_results.append(validated.model_dump(mode="json"))
                logger.info(f"  ✅ Validation PASSED after LLM: {validated.model_dump(mode='json')}")
            except ValidationError as e:
                human_review.append(
                    {
                        "file": file_path,
                        "ocr_text": ocr_text,
                        "extracted": extracted,
                        "validation_errors": e.errors(),
                    }
                )
                logger.error("  ⚠ Validation FAILED after LLM, marked for human review.")
                for err in e.errors():
                    field = err.get("loc")[0]
                    msg = err.get("msg")
                    val = extracted.get(field)
                    logger.error("    • Field '%s' with value '%s' failed: %s", field, val, msg)

        return valid_results, human_review
