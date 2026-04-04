"""Google Form — re-exports :mod:`config.settings` submit fields for the ``submit`` package."""

from __future__ import annotations

from config import settings

FORM_URL = settings.SUBMIT_FORM_URL
ENTRY_VENDOR = settings.SUBMIT_ENTRY_VENDOR
ENTRY_DATE = settings.SUBMIT_ENTRY_DATE
ENTRY_TOTAL = settings.SUBMIT_ENTRY_TOTAL
MAX_RETRIES = settings.SUBMIT_MAX_RETRIES
SUBMIT_DELAY = settings.SUBMIT_DELAY
DELAY = SUBMIT_DELAY
TIMEOUT = settings.SUBMIT_TIMEOUT
