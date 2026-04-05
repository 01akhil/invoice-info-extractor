"""Single Gemini call for multiple invoices (shared OCR text in one prompt)."""

from __future__ import annotations

from llm.gemini_llm import gemini_llm_call
from pipeline.llm_batch.batch_parser import parse_batch_llm_response
from pipeline.llm_batch.fallback import ocr_to_text
from pipeline.llm_batch.prompt_builder import build_batch_prompt


def merge_batch_strategies(strategies: list[str]) -> str:
    """Pick the strictest prompt variant present in the batch."""
    s = set(strategies or [])
    if "ocr_retry" in s:
        return "ocr_retry"
    if "after_validation_fail" in s:
        return "after_validation_fail"
    if "strict_json" in s:
        return "strict_json"
    return "default"


def run_batch_llm_extraction(
    items: list[tuple[str, str, list]],
    strategy: str,
) -> tuple[dict[str, dict] | None, str]:
    """
    ``items``: (job_id, image_path, ocr_results list).
    Returns (job_id -> {vendor, total, date}, raw_response).
    """
    triples: list[tuple[str, str, str]] = []
    for jid, path, ocr_results in items:
        triples.append((jid, path, ocr_to_text(ocr_results)))
    prompt = build_batch_prompt(triples, strategy=strategy)
    raw = gemini_llm_call(prompt)
    parsed = parse_batch_llm_response(raw or "")
    return parsed, raw or ""
