# Single place to load env and configure the Gemini client.

from __future__ import annotations

import os

import google.generativeai as genai
from dotenv import load_dotenv

from config.settings import GEMINI_MODEL

load_dotenv()

_configured = False


def _ensure_configured() -> None:
    global _configured
    if not _configured:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        _configured = True


def get_generative_model(model_name: str | None = None):
    """Return a GenerativeModel instance (configures API on first call)."""
    _ensure_configured()
    return genai.GenerativeModel(model_name or GEMINI_MODEL)
