"""Shared helpers for human-readable pipeline logs (grep for ``[pipeline]``)."""

from __future__ import annotations

from config.logger_setup import get_logger

_log = get_logger("pipeline")


def pl_info(stage: str, event: str, **fields: object) -> None:
    """Log one line: ``[pipeline] stage | event | k=v ...``."""
    parts = [f"[pipeline] {stage}", event]
    if fields:
        tail = " ".join(f"{k}={_fmt(v)}" for k, v in fields.items())
        parts.append(tail)
    _log.info(" | ".join(parts))


def pl_warning(stage: str, event: str, **fields: object) -> None:
    parts = [f"[pipeline] {stage}", event]
    if fields:
        tail = " ".join(f"{k}={_fmt(v)}" for k, v in fields.items())
        parts.append(tail)
    _log.warning(" | ".join(parts))


def pl_error(stage: str, event: str, **fields: object) -> None:
    """Hard failures (exceptions, terminal errors). Search logs for ``[pipeline]``."""
    parts = [f"[pipeline] {stage}", event]
    if fields:
        tail = " ".join(f"{k}={_fmt(v)}" for k, v in fields.items())
        parts.append(tail)
    _log.error(" | ".join(parts))


def _fmt(v: object) -> str:
    s = str(v)
    if len(s) > 200:
        return s[:197] + "..."
    return s
