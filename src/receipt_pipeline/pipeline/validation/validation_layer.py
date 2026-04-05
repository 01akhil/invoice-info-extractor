"""
Strict validation for pipeline (schema + business rules).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from receipt_pipeline.schemas.models import InvoiceValidation


@dataclass
class StrictValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    normalized: dict[str, Any] | None = None


MAX_REASONABLE_TOTAL = 1_000_000_000.0
MIN_REASONABLE_YEAR = 1990


def _is_vendor_non_numeric(v: str) -> bool:
    s = (v or "").strip()
    if not s:
        return False
    try:
        float(s.replace(",", ""))
        return False
    except ValueError:
        return True


def validate_extracted_invoice(
    file_path: str,
    vendor: Any,
    invoice_date: Any,
    total: Any,
) -> StrictValidationResult:
    """
    Vendor: non-empty, not purely numeric.
    Date: valid format, not in the future.
    Total: positive, within reasonable range.
    """
    errors: list[str] = []

    if vendor is None or (isinstance(vendor, str) and not vendor.strip()):
        errors.append("vendor_empty")
    elif isinstance(vendor, str) and not _is_vendor_non_numeric(vendor):
        errors.append("vendor_numeric_only")

    parsed_date: date | None = None
    if invoice_date is None:
        errors.append("date_missing")
    else:
        if isinstance(invoice_date, date):
            parsed_date = invoice_date
        elif isinstance(invoice_date, str):
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                try:
                    parsed_date = datetime.strptime(invoice_date.strip(), fmt).date()
                    break
                except ValueError:
                    continue
            if parsed_date is None:
                errors.append("date_invalid_format")
        else:
            errors.append("date_invalid_type")

    if parsed_date is not None:
        today = date.today()
        if parsed_date > today:
            errors.append("date_in_future")
        if parsed_date.year < MIN_REASONABLE_YEAR:
            errors.append("date_unreasonably_old")

    if total is None:
        errors.append("total_missing")
    else:
        try:
            t = float(total)
            if t <= 0:
                errors.append("total_not_positive")
            elif t > MAX_REASONABLE_TOTAL:
                errors.append("total_out_of_range")
        except (TypeError, ValueError):
            errors.append("total_invalid")

    if errors:
        return StrictValidationResult(ok=False, errors=errors)

    try:
        inv = InvoiceValidation(
            file=file_path,
            vendor=str(vendor).strip(),
            date=parsed_date.isoformat() if parsed_date else str(invoice_date),
            total=total,
        )
        dumped = inv.model_dump(mode="json")
        return StrictValidationResult(ok=True, normalized=dumped)
    except ValidationError as e:
        for err in e.errors():
            errors.append(f"pydantic:{err.get('loc')}:{err.get('msg')}")
        return StrictValidationResult(ok=False, errors=errors)
