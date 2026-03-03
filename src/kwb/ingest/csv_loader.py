"""
CSV ingestion with encoding detection and schema profiling.

This module turns raw files into profiled DatasetProfile objects.
It does NOT analyze quality — that's the analyze module's job.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

import pandas as pd

from kwb.core.models import ColumnProfile, DatasetProfile


def detect_encoding(path: Path) -> tuple[str, bool]:
    """Detect file encoding and BOM presence. Falls back to latin-1 for non-UTF-8 files."""
    raw = path.read_bytes()[:4096]
    has_bom = raw[:3] == b"\xef\xbb\xbf"
    if has_bom:
        return "utf-8-sig", True
    try:
        raw.decode("utf-8")
        return "utf-8", False
    except UnicodeDecodeError:
        return "latin-1", False


def detect_line_ending(path: Path) -> str:
    """Detect line ending style."""
    raw = path.read_bytes()[:4096]
    if b"\r\n" in raw:
        return "CRLF"
    elif b"\r" in raw:
        return "CR"
    return "LF"


def detect_id_column(df: pd.DataFrame) -> str | None:
    """Heuristic: find the column most likely to be the record identifier."""
    candidates = ["record_id", "id", "ID", "identifier", "Identifier", "obj_id"]

    def _is_likely_id(series: pd.Series) -> bool:
        """Check if a column is a plausible ID — tolerates minor issues."""
        non_empty = series[series.astype(str).str.strip() != ""]
        if len(non_empty) == 0:
            return False
        # Allow up to 0.5% duplicates or empties (real data is messy)
        unique_rate = non_empty.nunique() / len(non_empty)
        fill_rate = len(non_empty) / len(series)
        return unique_rate > 0.995 and fill_rate > 0.99

    for c in candidates:
        if c in df.columns and _is_likely_id(df[c]):
            return c
    # Fallback: first column that looks like an ID
    for c in df.columns:
        if _is_likely_id(df[c]):
            return c
    return None


def profile_column(series: pd.Series) -> ColumnProfile:
    """Build a statistical profile of a single column."""
    non_null = series.dropna()
    str_values = non_null.astype(str)
    lengths = str_values.str.len()

    sample = str_values.head(5).tolist() if len(str_values) > 0 else []

    return ColumnProfile(
        name=series.name,
        dtype=str(series.dtype),
        total_count=len(series),
        non_null_count=len(non_null),
        unique_count=int(series.nunique()),
        fill_rate=round(len(non_null) / len(series), 4) if len(series) > 0 else 0.0,
        sample_values=sample,
        value_lengths={
            "min": int(lengths.min()) if len(lengths) > 0 else 0,
            "max": int(lengths.max()) if len(lengths) > 0 else 0,
            "mean": round(float(lengths.mean()), 1) if len(lengths) > 0 else 0.0,
        },
    )


def ingest_csv(path: str | Path) -> tuple[pd.DataFrame, DatasetProfile]:
    """
    Load a CSV file and return both the DataFrame and its profile.

    Returns:
        (df, profile) — the raw data and its structural metadata.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    encoding, has_bom = detect_encoding(path)
    line_ending = detect_line_ending(path)

    df = pd.read_csv(path, encoding=encoding, dtype=str, keep_default_na=False)
    # Strip BOM artifacts from column names (common with Excel exports)
    df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
    # Treat empty strings as NaN for analysis purposes, but keep originals
    df_analysis = df.replace("", pd.NA)

    id_col = detect_id_column(df)
    columns = [profile_column(df_analysis[col]) for col in df.columns]

    profile = DatasetProfile(
        source_path=str(path),
        source_name=path.stem,
        row_count=len(df),
        column_count=len(df.columns),
        columns=columns,
        id_column=id_col,
        encoding_detected=encoding,
        has_bom=has_bom,
        line_ending=line_ending,
    )

    return df, profile
