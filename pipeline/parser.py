import json
import re

def parse_llm_response(response_text: str):
    try:
        match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if not match:
            return None

        data = json.loads(match.group())

        def _to_float(v):
            if v is None or v == "":
                return None
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v).strip().replace(",", "").replace("RM", "").replace("$", "").strip()
            return float(s)

        return {
            "vendor": data.get("vendor"),
            "total": _to_float(data.get("total")),
            "date": data.get("date"),
        }

    except Exception as e:
        print("[LLM Parse Error]", e)
        return None