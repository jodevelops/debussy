"""
XLSX Ingest — load Excel files for GLAM metadata.

Mirrors the csv_loader contract: returns (DataFrame, DatasetProfile)
with all-string columns and pd.NA for missing values.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from kwb.core.models import DatasetProfile

from kwb.ingest.csv_loader import (
    MAX_ROWS,
    profile_column,
    detect_id_column,
)

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".xlsx", ".xls"}


class XLSXLoadError(Exception):
    """Raised when an XLSX file cannot be loaded."""


def list_sheets(path: str | Path) -> list[str]:
    """Return the sheet names of an XLSX file."""
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise XLSXLoadError(
            f"Unsupported file type: {path.suffix}. "
            f"Expected one of {SUPPORTED_EXTENSIONS}"
        )
    try:
        import openpyxl
    except ImportError:
        raise XLSXLoadError(
            "openpyxl is required for XLSX support: pip install openpyxl"
        )
    wb = openpyxl.load_workbook(filename=str(path), read_only=True, data_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def load_xlsx(
    path: str | Path,
    max_rows: int = MAX_ROWS,
    sheet_name: str | int = 0,
) -> pd.DataFrame:
    """Load an XLSX file into a clean DataFrame (all-string columns)."""
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise XLSXLoadError(
            f"Unsupported file type: {path.suffix}. "
            f"Expected one of {SUPPORTED_EXTENSIONS}"
        )
    if not path.exists():
        raise XLSXLoadError(f"File not found: {path}")

    try:
        import openpyxl  # noqa: F401
    except ImportError:
        raise XLSXLoadError(
            "openpyxl is required for XLSX support: pip install openpyxl"
        )

    df = pd.read_excel(
        path,
        sheet_name=sheet_name,
        dtype=str,
        engine="openpyxl",
    )

    if len(df) > max_rows:
        raise XLSXLoadError(
            f"File has {len(df):,} rows, exceeding the limit of {max_rows:,}."
        )

    # Normalise missing values
    _NULLISH = {"", "nan", "NaN", "NULL", "None", "N/A", "n/a"}
    for col in df.columns:
        df[col] = df[col].fillna("")
        mask = df[col].isin(_NULLISH)
        if mask.any():
            df[col] = df[col].where(~mask, other=pd.NA)

    # Strip whitespace
    for col in df.columns:
        df[col] = df[col].apply(
            lambda v: v.strip() if isinstance(v, str) else v
        )

    logger.info(f"Loaded XLSX {path.name}: {len(df):,} rows × {len(df.columns)} cols")
    return df


def ingest_xlsx(
    path: str | Path,
    max_rows: int = MAX_ROWS,
    sheet_name: str | int = 0,
) -> tuple[pd.DataFrame, "DatasetProfile"]:
    """Load an XLSX and return (DataFrame, DatasetProfile)."""
    from kwb.core.models import DatasetProfile

    path = Path(path)
    df = load_xlsx(path, max_rows=max_rows, sheet_name=sheet_name)

    id_col = detect_id_column(df)
    columns = [profile_column(df[c]) for c in df.columns]

    profile = DatasetProfile(
        source_path=str(path),
        source_name=path.stem,
        row_count=len(df),
        column_count=len(df.columns),
        columns=columns,
        id_column=id_col,
        encoding_detected="utf-8",
        has_bom=False,
    )
    return df, profile
