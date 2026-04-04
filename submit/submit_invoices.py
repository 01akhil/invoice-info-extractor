"""
Legacy script entry; delegates to ``submit.service`` (same Google Form field mapping).

Prefer: ``python -m submit`` from project root.
"""

from __future__ import annotations

from pathlib import Path


def submit_to_google_form(json_file_path: str, delay: float = 0.5, max_retries: int = 3) -> None:
    """Submits ``valid_invoices`` only (human-review rows are not in that list)."""
    from submit.service import submit_from_export

    submit_from_export(json_file_path, delay_between=delay, max_retries=max_retries)


if __name__ == "__main__":
    import sys

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from submit.service import submit_from_export

    default = root / "results" / "upload" / "final_answer.json"
    path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else default
    submit_from_export(str(path))
