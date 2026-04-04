"""Maps failure type + previous strategy to the next improved LLM prompt strategy."""

from __future__ import annotations


def next_llm_strategy(failure_class: str, previous: str | None) -> str:
    if failure_class == "llm":
        if previous in (None, "", "default"):
            return "strict_json"
        if previous == "strict_json":
            return "ocr_retry"
        return "ocr_retry"
    if failure_class == "validation":
        if previous in (None, "", "default"):
            return "after_validation_fail"
        if previous == "after_validation_fail":
            return "strict_json"
        if previous == "strict_json":
            return "ocr_retry"
        return "ocr_retry"
    return "strict_json"
