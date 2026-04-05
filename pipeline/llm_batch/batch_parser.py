"""Parse multi-invoice JSON from batched LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("RM", "").replace("$", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_batch_llm_response(response_text: str) -> dict[str, dict[str, Any]] | None:
    """
    Expect JSON like:
    {"results": [{"job_id": "...", "vendor": "...", "total": 1.0, "date": "..."}, ...]}
    Returns map job_id -> {vendor, total, date}.
    """
    if not response_text or not response_text.strip():
        return None
    try:
        t = response_text.strip()
        if t.startswith("{"):
            try:
                data = json.loads(t)
            except json.JSONDecodeError:
                match = re.search(r"\{[\s\S]*\}", response_text, re.DOTALL)
                if not match:
                    return None
                data = json.loads(match.group())
        else:
            match = re.search(r"\{[\s\S]*\}", response_text, re.DOTALL)
            if not match:
                return None
            data = json.loads(match.group())
        results = data.get("results")
        if not isinstance(results, list):
            return None
        out: dict[str, dict[str, Any]] = {}
        for row in results:
            if not isinstance(row, dict):
                continue
            jid = row.get("job_id")
            if not jid:
                continue
            jid = str(jid).strip()
            out[jid] = {
                "vendor": row.get("vendor"),
                "total": _to_float(row.get("total")),
                "date": row.get("date"),
            }
        return out if out else None
    except Exception:
        return None
