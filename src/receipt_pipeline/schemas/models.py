"""Pydantic domain model — validation rules only (SRP)."""

from __future__ import annotations
from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator


class InvoiceValidation(BaseModel):
    file: str
    vendor: str = Field(..., min_length=2, max_length=100)
    date: date
    total: float = Field(..., ge=0)

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v):
        if v is None:
            raise ValueError("Date cannot be null")
        if isinstance(v, date):
            return v
        if not isinstance(v, str):
            raise ValueError("Invalid date type")
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(v, fmt).date()
            except ValueError:
                continue
        raise ValueError("Invalid date format")

    @field_validator("vendor")
    @classmethod
    def validate_vendor(cls, v):
        if not v or not v.strip():
            raise ValueError("Vendor cannot be empty")
        return v.strip()

    @field_validator("total", mode="before")
    @classmethod
    def validate_total(cls, v):
        if v is None:
            raise ValueError("Total cannot be null")
        return round(float(v), 2)
