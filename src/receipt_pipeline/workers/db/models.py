"""SQLAlchemy models for the invoice pipeline (idempotent by job_id)."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    OCR_DONE = "OCR_DONE"
    POST_OCR_DONE = "POST_OCR_DONE"
    LLM_PENDING = "LLM_PENDING"
    VALIDATING = "VALIDATING"
    SUCCESS = "SUCCESS"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    DLQ = "DLQ"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ExtractionSource(str, enum.Enum):
    OCR_RULE = "OCR_RULE"
    OCR_LLM = "OCR_LLM"
    LLM = "LLM"
    HUMAN = "HUMAN"
    UNKNOWN = "UNKNOWN"


class InvoiceJob(Base):
    __tablename__ = "invoice_jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    vendor: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.PENDING.value)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Total failure events allowed before NEEDS_REVIEW: 2 => one retry after first failure.
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attempt_strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ocr_snapshot: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    extraction_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    llm_last_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HumanCorrection(Base):
    """Audit trail for manual corrections (training / compliance)."""

    __tablename__ = "human_corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    vendor: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
