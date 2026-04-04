from __future__ import annotations

from llm.gemini_llm import gemini_llm_call
from pipeline.prompt_builder import build_prompt
from pipeline.parser import parse_llm_response


def ocr_to_text(ocr_results):
    texts = []
    for res in ocr_results:
        if isinstance(res, (list, tuple)) and len(res) >= 2:
            texts.append(res[1])
    return "\n".join(texts)


def run_llm_extraction(ocr_results, strategy: str = "default") -> tuple[dict | None, str]:
    """
    Always invoke LLM (used when the router already chose the LLM path).
    Returns (parsed dict or None, raw response text).
    """
    ocr_text = ocr_to_text(ocr_results)
    prompt = build_prompt(ocr_text, strategy=strategy)
    response = gemini_llm_call(prompt)
    parsed = parse_llm_response(response)
    return parsed, response or ""


def apply_llm_fallback(vendor_name, vendor_conf,
                       total_val, total_conf,
                       date_val, date_conf,
                       ocr_results):

    llm_triggered = False
    llm_parsed = None

    if (vendor_conf < 0.5) or (total_conf < 0.05) or (date_conf < 0.1):
        llm_triggered = True
        print("[Low confidence] LLM fallback triggered")

        parsed, _raw = run_llm_extraction(ocr_results, strategy="default")
        llm_parsed = parsed

        if parsed:
            print("[Parsed LLM]", parsed)

            if parsed.get("vendor"):
                vendor_name = parsed["vendor"]

            if parsed.get("total"):
                total_val = parsed["total"]

            if parsed.get("date"):
                date_val = parsed["date"]

    return vendor_name, total_val, date_val, llm_triggered, llm_parsed