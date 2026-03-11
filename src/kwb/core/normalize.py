"""Text normalization utilities for dictionary terms."""
from __future__ import annotations

import unicodedata


def normalize_term(text: str) -> str:
    """NFC normalize, collapse whitespace, trim.

    >>> normalize_term("  Johann   Sebastian   Bach  ")
    'Johann Sebastian Bach'
    """
    text = unicodedata.normalize("NFC", text)
    text = " ".join(text.split())
    return text.strip()
