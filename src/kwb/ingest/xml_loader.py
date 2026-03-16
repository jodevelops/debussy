"""
METS/MODS XML Ingest — parse METS/MODS metadata into a DataFrame.

Extracts mods:mods records from METS/MODS XML documents, producing
a DataFrame with one row per record and standard MODS fields as columns.
Uses stdlib xml.etree.ElementTree — no extra dependencies.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
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

# MODS namespace
NS = {
    "mods": "http://www.loc.gov/mods/v3",
    "mets": "http://www.loc.gov/METS/",
}


class XMLLoadError(Exception):
    """Raised when a METS/MODS XML file cannot be parsed."""


def _text(el: ET.Element | None) -> str:
    """Extract text from element, empty string if None."""
    if el is None:
        return ""
    return (el.text or "").strip()


def _extract_mods_record(mods: ET.Element) -> dict[str, str]:
    """Extract fields from a single mods:mods element."""
    record: dict[str, str] = {}

    # Title
    ti = mods.find("mods:titleInfo/mods:title", NS)
    record["title"] = _text(ti)

    # Subtitle
    sub = mods.find("mods:titleInfo/mods:subTitle", NS)
    record["subtitle"] = _text(sub)

    # Names (authors, creators)
    names = []
    for name_el in mods.findall("mods:name", NS):
        parts = []
        for np in name_el.findall("mods:namePart", NS):
            t = _text(np)
            if t:
                parts.append(t)
        if parts:
            names.append(", ".join(parts))
    record["name"] = "; ".join(names)

    # Role
    role_el = mods.find("mods:name/mods:role/mods:roleTerm", NS)
    record["role"] = _text(role_el)

    # Origin info
    place = mods.find("mods:originInfo/mods:place/mods:placeTerm", NS)
    record["place_of_origin"] = _text(place)

    publisher = mods.find("mods:originInfo/mods:publisher", NS)
    record["publisher"] = _text(publisher)

    date_issued = mods.find("mods:originInfo/mods:dateIssued", NS)
    record["date_issued"] = _text(date_issued)

    date_created = mods.find("mods:originInfo/mods:dateCreated", NS)
    record["date_created"] = _text(date_created)

    # Language
    lang = mods.find("mods:language/mods:languageTerm", NS)
    record["language"] = _text(lang)

    # Physical description
    form = mods.find("mods:physicalDescription/mods:form", NS)
    record["physical_form"] = _text(form)

    extent = mods.find("mods:physicalDescription/mods:extent", NS)
    record["extent"] = _text(extent)

    # Abstract / description
    abstract = mods.find("mods:abstract", NS)
    record["abstract"] = _text(abstract)

    # Subjects
    subjects = []
    for subj in mods.findall("mods:subject/mods:topic", NS):
        t = _text(subj)
        if t:
            subjects.append(t)
    for subj in mods.findall("mods:subject/mods:geographic", NS):
        t = _text(subj)
        if t:
            subjects.append(t)
    record["subjects"] = "; ".join(subjects)

    # Identifier
    identifiers = {}
    for id_el in mods.findall("mods:identifier", NS):
        id_type = id_el.get("type", "unknown")
        t = _text(id_el)
        if t:
            identifiers[id_type] = t
    record["identifier"] = identifiers.get(
        "local", identifiers.get("uri", next(iter(identifiers.values()), ""))
    )
    record["identifier_type"] = next(iter(identifiers.keys()), "")

    # Record info
    rec_id = mods.find("mods:recordInfo/mods:recordIdentifier", NS)
    record["record_id"] = _text(rec_id)

    # Access condition (rights)
    access = mods.find("mods:accessCondition", NS)
    record["access_condition"] = _text(access)

    # Note
    note = mods.find("mods:note", NS)
    record["note"] = _text(note)

    # Genre
    genre = mods.find("mods:genre", NS)
    record["genre"] = _text(genre)

    # Type of resource
    tor = mods.find("mods:typeOfResource", NS)
    record["type_of_resource"] = _text(tor)

    return record


def load_mets_mods(path: str | Path, max_rows: int = MAX_ROWS) -> pd.DataFrame:
    """Parse a METS/MODS XML file into a DataFrame."""
    path = Path(path)
    if not path.exists():
        raise XMLLoadError(f"File not found: {path}")

    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        raise XMLLoadError(f"Invalid XML: {e}") from e

    root = tree.getroot()

    # Find all mods:mods elements (can be inside mets:dmdSec or standalone)
    mods_records = root.findall(".//mods:mods", NS)

    # If no namespaced MODS found, try without namespace
    if not mods_records:
        mods_records = root.findall(".//{http://www.loc.gov/mods/v3}mods")

    # Also try plain (no namespace) as fallback
    if not mods_records:
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if tag == "mods":
                mods_records.append(el)

    if not mods_records:
        raise XMLLoadError(
            "No mods:mods elements found in XML. "
            "Expected METS/MODS format."
        )

    if len(mods_records) > max_rows:
        raise XMLLoadError(
            f"XML contains {len(mods_records):,} records, "
            f"exceeding the limit of {max_rows:,}."
        )

    rows = [_extract_mods_record(m) for m in mods_records]
    df = pd.DataFrame(rows)

    # Convert empty strings to pd.NA
    for col in df.columns:
        mask = df[col] == ""
        if mask.any():
            df[col] = df[col].where(~mask, other=pd.NA)

    # Drop columns that are entirely empty
    df = df.dropna(axis=1, how="all")

    logger.info(
        f"Loaded METS/MODS {path.name}: {len(df)} records, "
        f"{len(df.columns)} fields"
    )
    return df


def ingest_xml(
    path: str | Path,
    max_rows: int = MAX_ROWS,
) -> tuple[pd.DataFrame, "DatasetProfile"]:
    """Load a METS/MODS XML and return (DataFrame, DatasetProfile)."""
    from kwb.core.models import DatasetProfile

    path = Path(path)
    df = load_mets_mods(path, max_rows=max_rows)

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
