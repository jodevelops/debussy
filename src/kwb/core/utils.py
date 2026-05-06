"""
Shared utility functions for Debussy.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with timezone offset.

    Single source of truth for timestamps across the codebase. All persisted
    timestamps (workspace, tasks, image reviews, AI runs, …) use this helper
    so the format is consistent and the resulting strings are always
    timezone-aware. Replaces the deprecated ``datetime.utcnow()`` call which
    produced naive datetimes and triggers a ``DeprecationWarning`` in
    Python 3.12+.

    The output looks like ``"2026-05-05T14:23:11.123456+00:00"``.
    """
    return datetime.now(timezone.utc).isoformat()


def try_parse_json(text: str | None) -> dict[str, Any] | list | None:
    """
    Try to parse JSON from an LLM response, handling common issues.

    Strips BOM, leading whitespace, and markdown code fences (```json ... ```)
    before parsing. Returns None on parse failure or if result is a scalar.
    """
    if text is None:
        return None
    text = text.strip().lstrip("\ufeff")
    if text.startswith("```"):
        # Strip opening fence line (```json, ```, etc.)
        first_nl = text.find("\n")
        if first_nl == -1:
            text = ""
        else:
            text = text[first_nl + 1:]
        # Strip closing fence if present
        if text.endswith("```"):
            text = text[: text.rfind("```")].rstrip()
        text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, (dict, list)):
            return result
        return None
    except (json.JSONDecodeError, ValueError):
        return None


def truncate_string(text: str, max_len: int = 100, ellipsis: str = "…") -> str:
    """
    Truncate *text* to at most *max_len* characters.
    If truncation occurs, replaces the last character(s) with *ellipsis*.
    """
    if not text or len(text) <= max_len:
        return text
    return text[: max_len - len(ellipsis)] + ellipsis


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert *value* to float, returning *default* on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """
    Convert *value* to int, returning *default* on failure.
    Float strings are truncated: safe_int("3.9") → 3.
    """
    if value is None:
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def mask_secret(value: str, visible: int = 4) -> str:
    """Return *value* with all but the first *visible* characters replaced by asterisks."""
    if not value:
        return "(nicht gesetzt)"
    if len(value) <= visible:
        return "*" * len(value)
    return value[:visible] + "*" * (len(value) - visible)


# Keep old private alias so existing imports work without breakage
_try_parse_json = try_parse_json
