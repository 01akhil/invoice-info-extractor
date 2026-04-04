def build_prompt(ocr_text: str, strategy: str = "default") -> str:
    """Build LLM prompt; `strategy` selects stricter or OCR-recovery wording."""
    if strategy == "strict_json":
        return _prompt_strict_json(ocr_text)
    if strategy == "after_validation_fail":
        return _prompt_validation_retry(ocr_text)
    if strategy == "ocr_retry":
        return _prompt_ocr_recovery(ocr_text)
    return _prompt_default(ocr_text)


def _prompt_default(ocr_text: str) -> str:
    return f"""
You are a highly skilled invoice data extraction assistant.

Extract the following fields from the invoice text:

1. **Vendor Name**:
   - Extract the full name of the vendor as it appears.
   - Ignore any addresses, phone numbers, or extra details.
   - If unknown, use an empty string: "".

2. Total Amount To Pay

3. **Invoice Date**:
   - Use the format YYYY-MM-DD.
   - Accept common formats (DD/MM/YYYY, MM-DD-YYYY) and convert to ISO format.
   - If not found, use null.

4. **General Rules**:
   - Ignore irrelevant headers, footers, and OCR artifacts.
   - Focus only on printed text; ignore handwritten text, stamps, or other marks.
   - Correct obvious OCR errors where possible (e.g., 'O' → '0', 'I' → '1').
   - Do not include any extra fields, comments, or text outside the JSON.
   - If any field cannot be determined reliably, use empty string "" for text or null for numbers/dates.

Return ONLY in valid JSON:
{{
  "vendor": "...",
  "total": "...",
  "date": "..."
}}


Invoice Text:
{ocr_text}
"""


def _prompt_strict_json(ocr_text: str) -> str:
    return f"""
Return a single JSON object only. No markdown, no code fences, no prose.
Keys: "vendor" (string), "total" (number or null), "date" (string YYYY-MM-DD or null).
Rules: vendor must not be only digits. total must be positive if present. date must not be in the future.

OCR text:
{ocr_text}
"""


def _prompt_validation_retry(ocr_text: str) -> str:
    return f"""
Previous extraction failed validation. Extract again with extra care:
- vendor: company name, not a number, at least 2 characters if present.
- total: numeric amount to pay, positive.
- date: YYYY-MM-DD only; must not be after today's date.

Return ONLY JSON: {{"vendor":"...","total":<number or null>,"date":"YYYY-MM-DD or null"}}

Invoice text:
{ocr_text}
"""


def _prompt_ocr_recovery(ocr_text: str) -> str:
    return f"""
OCR quality may be poor. Infer vendor, total, and date; fix common OCR confusions (O/0, l/1).
Return ONLY JSON: {{"vendor":"...","total":<number or null>,"date":"YYYY-MM-DD or null"}}

Text:
{ocr_text}
"""


def build_batch_prompt(
    items: list[tuple[str, str, str]],
    strategy: str = "default",
) -> str:
    """
    Build one prompt for multiple invoices.
    Each item is (job_id, image_path, ocr_text).
    Model must return JSON with a ``results`` array; each element must include the exact ``job_id``.
    """
    blocks: list[str] = []
    for i, (jid, path, text) in enumerate(items, 1):
        blocks.append(
            f"### Invoice {i}\n"
            f"- job_id (must copy exactly into JSON): `{jid}`\n"
            f"- file: {path}\n\n"
            f"OCR text:\n{text}\n"
        )
    body = "\n".join(blocks)
    extra = _batch_strategy_notes(strategy)
    return f"""You extract **vendor name**, **total amount to pay**, and **invoice date** for EACH invoice below.
The invoices are independent; do not mix fields between them.

Return ONLY valid JSON (no markdown fences) in exactly this shape:
{{
  "results": [
    {{
      "job_id": "<exact uuid from the invoice block>",
      "vendor": "string or empty",
      "total": <number or null>,
      "date": "YYYY-MM-DD or null"
    }}
  ]
}}

Rules:
- ``results`` must have one object per invoice block below, in the same order.
- ``job_id`` must match the invoice block exactly.
- Vendor must not be only digits. Total must be positive if present. Date must not be in the future.
- If a field cannot be determined, use "" for vendor or null for total/date.

{extra}
--- Invoices ---

{body}
"""


def _batch_strategy_notes(strategy: str) -> str:
    if strategy == "strict_json":
        return "Be strict: JSON only; no prose."
    if strategy == "after_validation_fail":
        return "Previous validation failed: vendor at least 2 chars if present; total positive; date ISO and not future."
    if strategy == "ocr_retry":
        return "OCR may be noisy; fix O/0 and similar confusions per invoice."
    return ""