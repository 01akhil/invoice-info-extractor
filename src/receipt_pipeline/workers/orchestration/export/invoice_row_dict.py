"""Map an ``InvoiceJob`` ORM row to the flat dict used in exports."""

from __future__ import annotations

from typing import Any

from receipt_pipeline.db.models import InvoiceJob


def invoice_row_to_flat_dict(r: InvoiceJob) -> dict[str, Any]:
    return {
        "job_id": r.job_id,
        "file": r.image_path,
        "vendor": r.vendor,
        "date": r.invoice_date,
        "total": r.total_amount,
        "confidence": r.confidence,
        "source": r.source,
        "status": r.status,
        "retry_count": r.retry_count,
        "last_error": r.last_error,
    }
