"""
XML Ingest — parse METS/MODS and LIDO metadata into a DataFrame.

Extracts records from METS/MODS or LIDO XML documents, producing
a DataFrame with one row per record and standard fields as columns.
Format is auto-detected from the root element.
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

# Namespaces
NS = {
    "mods": "http://www.loc.gov/mods/v3",
    "mets": "http://www.loc.gov/METS/",
    "lido": "http://www.lido-schema.org",
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


# ---------------------------------------------------------------------------
# LIDO (Lightweight Information Describing Objects) — museum metadata
# ---------------------------------------------------------------------------


def _lido_find(parent: ET.Element, path: str) -> ET.Element | None:
    """Find a child by LIDO-namespaced path with bare-tag fallback."""
    el = parent.find(path, NS)
    if el is not None:
        return el
    # Fallback: strip namespace prefixes, match by local name
    parts = [p.split(":")[-1] for p in path.split("/")]
    current = parent
    for part in parts:
        found = None
        for child in current.iter():
            if child is current:
                continue
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == part:
                # Only accept direct descendants in path order
                found = child
                break
        if found is None:
            return None
        current = found
    return current


def _lido_findall(parent: ET.Element, path: str) -> list[ET.Element]:
    """Find all elements matching a LIDO path; fall back to local-name match."""
    els = parent.findall(path, NS)
    if els:
        return els
    # Fallback: match only by terminal local name
    terminal = path.split("/")[-1].split(":")[-1]
    out: list[ET.Element] = []
    for el in parent.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == terminal:
            out.append(el)
    return out


def _extract_lido_record(lido: ET.Element) -> dict[str, str]:
    """Extract fields from a single lido:lido element."""
    record: dict[str, str] = {}

    # Title — descriptiveMetadata/objectIdentificationWrap/titleWrap/titleSet/appellationValue
    titles = []
    for av in _lido_findall(
        lido,
        "lido:descriptiveMetadata/lido:objectIdentificationWrap/lido:titleWrap/"
        "lido:titleSet/lido:appellationValue",
    ):
        t = _text(av)
        if t:
            titles.append(t)
    record["title"] = "; ".join(titles)

    # Record ID — administrativeMetadata/recordWrap/recordID
    rec_id = _lido_find(
        lido,
        "lido:administrativeMetadata/lido:recordWrap/lido:recordID",
    )
    record["record_id"] = _text(rec_id)

    # Abstract — descriptiveNoteValue (joined)
    abstracts = []
    for nv in _lido_findall(
        lido,
        "lido:descriptiveMetadata/lido:objectIdentificationWrap/"
        "lido:objectDescriptionWrap/lido:objectDescriptionSet/"
        "lido:descriptiveNoteValue",
    ):
        t = _text(nv)
        if t:
            abstracts.append(t)
    record["abstract"] = "; ".join(abstracts)

    # Production event → name, role, date_created, place_of_origin
    names, roles, dates_created, places = [], [], [], []
    for event in _lido_findall(
        lido,
        "lido:descriptiveMetadata/lido:eventWrap/lido:eventSet/lido:event",
    ):
        # Limit to production events when eventType is specified
        etype = _lido_find(event, "lido:eventType/lido:term")
        etype_text = _text(etype).lower() if etype is not None else ""
        if etype_text and etype_text != "production":
            continue
        for actor_av in _lido_findall(
            event,
            "lido:eventActor/lido:actorInRole/lido:actor/lido:nameActorSet/"
            "lido:appellationValue",
        ):
            t = _text(actor_av)
            if t:
                names.append(t)
        for role_term in _lido_findall(
            event,
            "lido:eventActor/lido:actorInRole/lido:roleActor/lido:term",
        ):
            t = _text(role_term)
            if t:
                roles.append(t)
        for dt in _lido_findall(event, "lido:eventDate/lido:displayDate"):
            t = _text(dt)
            if t:
                dates_created.append(t)
        for pl in _lido_findall(event, "lido:eventPlace/lido:displayPlace"):
            t = _text(pl)
            if t:
                places.append(t)
    record["name"] = "; ".join(names)
    record["role"] = "; ".join(roles)
    record["date_created"] = "; ".join(dates_created)
    record["place_of_origin"] = "; ".join(places)

    # Subjects — objectRelationWrap/subjectWrap/subjectSet/subject/subjectConcept/term
    subjects = []
    for term in _lido_findall(
        lido,
        "lido:descriptiveMetadata/lido:objectRelationWrap/lido:subjectWrap/"
        "lido:subjectSet/lido:subject/lido:subjectConcept/lido:term",
    ):
        t = _text(term)
        if t:
            subjects.append(t)
    record["subjects"] = "; ".join(subjects)

    # Genre / object work type
    genres = []
    for term in _lido_findall(
        lido,
        "lido:descriptiveMetadata/lido:objectClassificationWrap/"
        "lido:objectWorkTypeWrap/lido:objectWorkType/lido:term",
    ):
        t = _text(term)
        if t:
            genres.append(t)
    record["genre"] = "; ".join(genres)

    # Extent — displayObjectMeasurements
    extents = []
    for meas in _lido_findall(
        lido,
        "lido:descriptiveMetadata/lido:objectIdentificationWrap/"
        "lido:objectMeasurementsWrap/lido:objectMeasurementsSet/"
        "lido:displayObjectMeasurements",
    ):
        t = _text(meas)
        if t:
            extents.append(t)
    record["extent"] = "; ".join(extents)

    # Access condition — rightsType term
    rights = []
    for term in _lido_findall(
        lido,
        "lido:administrativeMetadata/lido:rightsWorkWrap/lido:rightsWorkSet/"
        "lido:rightsType/lido:term",
    ):
        t = _text(term)
        if t:
            rights.append(t)
    record["access_condition"] = "; ".join(rights)

    return record


def load_lido(path: str | Path, max_rows: int = MAX_ROWS) -> pd.DataFrame:
    """Parse a LIDO XML file into a DataFrame (one row per lido:lido)."""
    path = Path(path)
    if not path.exists():
        raise XMLLoadError(f"File not found: {path}")

    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        raise XMLLoadError(f"Invalid XML: {e}") from e

    root = tree.getroot()

    lido_records = root.findall(".//lido:lido", NS)
    if not lido_records:
        lido_records = root.findall(".//{http://www.lido-schema.org}lido")
    if not lido_records:
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if tag == "lido":
                lido_records.append(el)

    if not lido_records:
        raise XMLLoadError(
            "No lido:lido elements found in XML. Expected LIDO format."
        )

    if len(lido_records) > max_rows:
        raise XMLLoadError(
            f"XML contains {len(lido_records):,} records, "
            f"exceeding the limit of {max_rows:,}."
        )

    rows = [_extract_lido_record(el) for el in lido_records]
    df = pd.DataFrame(rows)

    for col in df.columns:
        mask = df[col] == ""
        if mask.any():
            df[col] = df[col].where(~mask, other=pd.NA)
    df = df.dropna(axis=1, how="all")

    logger.info(
        f"Loaded LIDO {path.name}: {len(df)} records, {len(df.columns)} fields"
    )
    return df


# ---------------------------------------------------------------------------
# Format detection + dispatch
# ---------------------------------------------------------------------------


def detect_xml_format(path: str | Path) -> str:
    """Detect XML format from root element.

    Returns one of: "mets_mods", "mods", "lido", "unknown".
    Inspects only the root element to stay cheap on large files.
    """
    path = Path(path)
    try:
        for event, el in ET.iterparse(str(path), events=("start",)):
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            ns = el.tag.split("}")[0].lstrip("{") if "}" in el.tag else ""
            if tag == "mets" or ns == NS["mets"]:
                return "mets_mods"
            if tag in ("mods", "modsCollection") or ns == NS["mods"]:
                return "mods"
            if tag in ("lido", "lidoWrap") or ns == NS["lido"]:
                return "lido"
            # Only inspect the root element
            return "unknown"
    except ET.ParseError as e:
        raise XMLLoadError(f"Invalid XML: {e}") from e
    return "unknown"


def ingest_xml(
    path: str | Path,
    max_rows: int = MAX_ROWS,
) -> tuple[pd.DataFrame, "DatasetProfile"]:
    """Load METS/MODS or LIDO XML and return (DataFrame, DatasetProfile)."""
    from kwb.core.models import DatasetProfile

    path = Path(path)
    fmt = detect_xml_format(path)
    if fmt == "lido":
        df = load_lido(path, max_rows=max_rows)
    elif fmt in ("mets_mods", "mods"):
        df = load_mets_mods(path, max_rows=max_rows)
    else:
        raise XMLLoadError(
            f"Unrecognized XML format (root not METS/MODS or LIDO): {path.name}"
        )

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
