"""
Strict validation for pipeline (schema + business rules).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from pydantic import ValidationError
from receipt_pipeline.schemas.models import InvoiceValidation


# Result object returned by validator

@dataclass
class StrictValidationResult:
    ok: bool  # True if validation passed, False otherwise
    errors: list[str] = field(default_factory=list)  # List of validation errors
    normalized: dict[str, Any] | None = None  # Cleaned + structured output (if valid)



# Business rule limits

MAX_REASONABLE_TOTAL = 1_000_000_000.0  # Upper bound for invoice total
MIN_REASONABLE_YEAR = 1990  # Reject dates older than this


# -------------------------------
# Helper: check vendor is not just a number
# -------------------------------
def _is_vendor_non_numeric(v: str) -> bool:
    """
    Returns True if vendor is NOT purely numeric.
    Example:
        "12345"  -> False (invalid vendor)
        "Dominos" -> True (valid vendor)
    """
    s = (v or "").strip()
    if not s:
        return False
    try:
        float(s.replace(",", ""))  # Try converting to number
        return False  # If conversion works → it's numeric → invalid
    except ValueError:
        return True  # Not numeric → valid vendor


# Main validation function
def validate_extracted_invoice(
    file_path: str,
    vendor: Any,
    invoice_date: Any,
    total: Any,
) -> StrictValidationResult:
    """
    Validates extracted invoice fields using:
    - Basic checks (empty, type)
    - Business rules (date range, total range)
    - Schema validation (Pydantic)

    Rules:
    Vendor → non-empty, not purely numeric
    Date   → valid format, not future, not too old
    Total  → positive, within reasonable range
    """

    errors: list[str] = []

    # 1. Vendor validation

    if vendor is None or (isinstance(vendor, str) and not vendor.strip()):
        errors.append("vendor_empty")  # Missing vendor
    elif isinstance(vendor, str) and not _is_vendor_non_numeric(vendor):
        errors.append("vendor_numeric_only") 
   
    # 2. Date parsing + validation
   
    parsed_date: date | None = None

    if invoice_date is None:
        errors.append("date_missing")

    else:
        # If already a date object → accept directly
        if isinstance(invoice_date, date):
            parsed_date = invoice_date

        # If string → try parsing multiple formats
        elif isinstance(invoice_date, str):
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                try:
                    parsed_date = datetime.strptime(invoice_date.strip(), fmt).date()
                    break  # Stop once parsed successfully
                except ValueError:
                    continue

            # If no format matched
            if parsed_date is None:
                errors.append("date_invalid_format")

        else:
            errors.append("date_invalid_type")


    # 3. Date business rules
    
    if parsed_date is not None:
        today = date.today()

        if parsed_date > today:
            errors.append("date_in_future")

        if parsed_date.year < MIN_REASONABLE_YEAR:
            errors.append("date_unreasonably_old")

    # 4. Total validation
  
    if total is None:
        errors.append("total_missing")

    else:
        try:
            t = float(total)  # Convert to number

            if t <= 0:
                errors.append("total_not_positive")

            elif t > MAX_REASONABLE_TOTAL:
                errors.append("total_out_of_range")

        except (TypeError, ValueError):
            errors.append("total_invalid")  # Cannot convert to float

  
    # 5. If any errors → fail early
 
    if errors:
        return StrictValidationResult(ok=False, errors=errors)


    # 6. Final schema validation (Pydantic)
 
    try:
        inv = InvoiceValidation(
            file=file_path,
            vendor=str(vendor).strip(),
            date=parsed_date.isoformat() if parsed_date else str(invoice_date),
            total=total,
        )

        # Convert to clean JSON-ready dict
        dumped = inv.model_dump(mode="json")

        return StrictValidationResult(
            ok=True,
            normalized=dumped  # Clean structured output
        )

    # -------------------------------
    # 7. If schema validation fails
    # -------------------------------
    except ValidationError as e:
        for err in e.errors():
            errors.append(f"pydantic:{err.get('loc')}:{err.get('msg')}")

        return StrictValidationResult(ok=False, errors=errors)