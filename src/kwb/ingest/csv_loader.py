"""
CSV/TSV Ingest — robust loader for GLAM metadata exports.

DESIGN:
- All string columns are loaded as dtype=str (avoids Pandas mixed-type warnings).
- Empty cells are always pd.NA (not np.nan, not None, not "nan").
- BOM detection and automatic stripping.
- Semicolon-list splitting utilities for multi-valued fields.
- Max-row guard with clear error message.

FIXES vs original csv_loader.py:
- No more keep_default_na=False + manual replace("", pd.NA) inconsistency.
  Strategy: load everything as str, then replace "" and "nan" with pd.NA.
- Mixed-type dtype warnings from the GND-merged CSV are resolved by
  forcing all object columns to str.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from kwb.core.models import ColumnProfile, DatasetProfile

logger = logging.getLogger(__name__)

MAX_ROWS = 50_000
SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".txt"}


class CSVLoadError(Exception):
    """Raised when a CSV cannot be loaded for a known reason."""


def detect_encoding(path: str | Path) -> tuple[str, bool]:
    """
    Detect file encoding and BOM presence.

    Returns (encoding_name, has_bom).
    Falls back to "utf-8" if chardet is not installed.
    """
    path = Path(path)
    raw = path.read_bytes()

    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", True
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le", True
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be", True

    try:
        import chardet
        result = chardet.detect(raw[:8192])
        enc = result.get("encoding") or "utf-8"
        return enc, False
    except ImportError:
        return "utf-8", False


def _sniff_delimiter(sample: str) -> str:
    """Sniff delimiter from a CSV sample; default to comma."""
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


def load_csv(
    path: str | Path,
    max_rows: int = MAX_ROWS,
    encoding: str | None = None,
    delimiter: str | None = None,
    id_column: str | None = None,
) -> pd.DataFrame:
    """
    Load a CSV/TSV file into a clean, consistent DataFrame.

    All columns are returned as str | pd.NA (never np.nan, "nan", or None
    for missing values). Integer/float columns that contain actual numeric
    data keep their type; purely numeric ID columns are preserved as str.

    Raises CSVLoadError for known failure modes.
    """
    path = Path(path)

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise CSVLoadError(
            f"Unsupported file type: {path.suffix}. "
            f"Expected one of {SUPPORTED_EXTENSIONS}"
        )

    if not path.exists():
        raise CSVLoadError(f"File not found: {path}")

    enc, has_bom = (encoding, False) if encoding else detect_encoding(path)

    # Sniff delimiter from first 4 KB
    try:
        with open(path, encoding=enc, errors="replace") as fh:
            sample = fh.read(4096)
    except Exception as e:
        raise CSVLoadError(f"Cannot read file: {e}") from e

    delim = delimiter or _sniff_delimiter(sample)

    # Load as str to avoid mixed-type warnings (e.g. GND confidence "70%")
    # Try detected encoding first, then fall back to common European encodings.
    _encoding_candidates = [enc] + [e for e in ("utf-8", "cp1252", "latin-1") if e != enc]
    df = None
    last_err: Exception | None = None
    for candidate_enc in _encoding_candidates:
        try:
            df = pd.read_csv(
                path,
                sep=delim,
                encoding=candidate_enc,
                dtype=str,
                keep_default_na=False,     # don't convert "" → NaN automatically
                na_values=[],              # we handle NA ourselves
                engine="python",           # handles mixed delimiters gracefully
            )
            enc = candidate_enc  # remember which encoding actually worked
            break
        except (UnicodeDecodeError, pd.errors.ParserError) as e:
            last_err = e
            continue
    if df is None:
        raise CSVLoadError(f"Cannot decode file (tried {_encoding_candidates}): {last_err}") from last_err

    if len(df) > max_rows:
        raise CSVLoadError(
            f"File has {len(df):,} rows, exceeding the limit of {max_rows:,}. "
            f"Split the file or raise MAX_ROWS."
        )

    # Normalise missing values: "", "nan", "NaN", "NULL", "None" → pd.NA
    _NULLISH = {"", "nan", "NaN", "NULL", "None", "N/A", "n/a"}
    for col in df.columns:
        mask = df[col].isin(_NULLISH)
        if mask.any():
            df[col] = df[col].where(~mask, other=pd.NA)

    # Strip leading/trailing whitespace from string columns
    for col in df.columns:
        df[col] = df[col].apply(
            lambda v: v.strip() if isinstance(v, str) else v
        )

    # Ensure id_column (if given) is str even if Pandas inferred numeric
    if id_column and id_column in df.columns:
        df[id_column] = df[id_column].astype(str)

    logger.info(
        f"Loaded {path.name}: {len(df):,} rows × {len(df.columns)} cols "
        f"(enc={enc}, delim={repr(delim)})"
    )
    return df


def split_multivalued(df: pd.DataFrame, columns: list[str], sep: str = ";") -> pd.DataFrame:
    """
    For each listed column, explode semicolon-separated values into multiple rows.

    Example:
        "Felder; Getreide" → two rows, one per term.
    """
    working = df.copy()
    for col in columns:
        if col not in working.columns:
            continue
        working[col] = working[col].apply(
            lambda v: [t.strip() for t in str(v).split(sep) if t.strip()]
            if isinstance(v, str) else []
        )
        # Explode the column; other columns are duplicated per entry
        working = working.explode(col, ignore_index=True)
        # Empty lists → pd.NA
        working[col] = working[col].apply(
            lambda v: pd.NA if not v else v
        )
    return working


def fill_rate(df: pd.DataFrame) -> dict[str, float]:
    """Return fill rate (0.0–1.0) per column."""
    n = len(df)
    if n == 0:
        return {col: 0.0 for col in df.columns}
    return {
        col: df[col].notna().sum() / n
        for col in df.columns
    }


def profile_csv(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Quick column profile for QA display."""
    rates = fill_rate(df)
    result = []
    for col in df.columns:
        non_null = df[col].dropna()
        unique_count = non_null.nunique() if len(non_null) > 0 else 0
        result.append({
            "column": col,
            "fill_rate": round(rates[col], 4),
            "non_null": int(non_null.count()),
            "unique": int(unique_count),
            "sample": non_null.head(3).tolist(),
        })
    return result


# ---------------------------------------------------------------------------
# Column profiling (returns ColumnProfile model)
# ---------------------------------------------------------------------------

def profile_column(series: pd.Series) -> "ColumnProfile":
    """Build a ColumnProfile for a single DataFrame column."""
    from kwb.core.models import ColumnProfile

    non_null = series.dropna()
    total = len(series)
    nn_count = int(non_null.count())
    unique = int(non_null.nunique()) if nn_count > 0 else 0
    rate = nn_count / total if total > 0 else 0.0

    lengths: dict[str, int] = {}
    if nn_count > 0 and series.dtype == object:
        str_lens = non_null.astype(str).str.len()
        lengths = {
            "min": int(str_lens.min()),
            "max": int(str_lens.max()),
            "mean": int(str_lens.mean()),
        }

    return ColumnProfile(
        name=str(series.name),
        dtype=str(series.dtype),
        total_count=total,
        non_null_count=nn_count,
        unique_count=unique,
        fill_rate=round(rate, 4),
        sample_values=non_null.head(3).tolist(),
        value_lengths=lengths,
    )


# ---------------------------------------------------------------------------
# ID column detection
# ---------------------------------------------------------------------------

_ID_PATTERNS = [
    "record_id", "id", "identifier", "signatur", "inventarnummer",
    "inventar_nr", "inv_nr", "object_id", "obj_id", "catalogue_id",
]


def detect_id_column(df: pd.DataFrame) -> str | None:
    """Heuristic detection of the ID column in a DataFrame.

    Checks column names against known patterns first, then falls back
    to finding a column where every value is unique.
    """
    lower_cols = {c.lower(): c for c in df.columns}
    for pat in _ID_PATTERNS:
        if pat in lower_cols:
            col = lower_cols[pat]
            if df[col].dropna().is_unique:
                return col

    # Fallback: first fully-unique column
    for col in df.columns:
        non_null = df[col].dropna()
        if len(non_null) > 0 and non_null.is_unique:
            return col
    return None


# ---------------------------------------------------------------------------
# High-level ingest (load + profile)
# ---------------------------------------------------------------------------

def ingest_csv(
    path: str | Path,
    max_rows: int = MAX_ROWS,
) -> tuple[pd.DataFrame, "DatasetProfile"]:
    """Load a CSV and return (DataFrame, DatasetProfile).

    Convenience wrapper used by CLI and API.
    """
    from kwb.core.models import DatasetProfile

    path = Path(path)
    enc, has_bom = detect_encoding(path)
    df = load_csv(path, max_rows=max_rows)

    id_col = detect_id_column(df)
    columns = [profile_column(df[c]) for c in df.columns]

    profile = DatasetProfile(
        source_path=str(path),
        source_name=path.stem,
        row_count=len(df),
        column_count=len(df.columns),
        columns=columns,
        id_column=id_col,
        encoding_detected=enc,
        has_bom=has_bom,
    )
    return df, profile

