"""
Shared utility functions for Debussy.
"""
from __future__ import annotations
import json
from typing import Any


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


# Keep old private alias so existing imports work without breakage
_try_parse_json = try_parse_json
