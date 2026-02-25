"""
Goobi-Import XML export.

Generates XML files in the goobi-import format from curated workspace data.
Schema based on sample1_goobi.xml.

Each record becomes one <goobi-import> document with:
- <data type="MuseumObject"> containing metadata, persons, corporates
- <process> with title and properties
"""
from __future__ import annotations

import logging
from xml.etree.ElementTree import Element, SubElement, tostring, indent
from typing import Any

import pandas as pd

from kwb.core.workspace import Workspace, CuratedEntity

logger = logging.getLogger(__name__)

# Default field → Goobi metadata type mapping
DEFAULT_FIELD_MAP = {
    "record_id": ("Identifier", "CatalogIDDigital"),
    "title": ("Titel", "TitleDocMain"),
    "description": ("Beschreibung", "Description"),
    "date": ("Erscheinungsjahr", "PublicationYear"),
    "language": ("Language", "DocLanguage"),
    "collection": ("Sammlung", "singleDigCollection"),
}

# NER type → Goobi person/corporate role mapping
ENTITY_ROLE_MAP = {
    "PER": "Author",
    "ORG": "CorporateArtist",
}

GND_URI_BASE = "http://d-nb.info/gnd/"


def export_goobi_xml(
    df: pd.DataFrame,
    workspace: Workspace,
    record_id_col: str = "record_id",
    field_map: dict[str, tuple[str, str]] | None = None,
    data_type: str = "MuseumObject",
) -> list[tuple[str, str]]:
    """
    Export records as Goobi-Import XML.

    Args:
        df: Source DataFrame
        workspace: Workspace with curated entities, dates, dictionary
        record_id_col: Column containing record IDs
        field_map: {csv_column: (goobi_label, goobi_type)} mapping
        data_type: Goobi data type (MuseumObject, Monograph, etc.)

    Returns:
        List of (record_id, xml_string) tuples
    """
    fmap = field_map or workspace.field_mapping or {}
    # Build entity lookup: record_id → [entities]
    entities_by_record: dict[str, list[CuratedEntity]] = {}
    for e in workspace.entities:
        if e.status != "rejected":
            entities_by_record.setdefault(e.record_id, []).append(e)

    # Build EDTF lookup: record_id → edtf
    dates_by_record: dict[str, str] = {}
    for d in workspace.dates:
        if d.status != "rejected" and d.edtf:
            dates_by_record[d.record_id] = d.edtf

    results = []

    for _, row in df.iterrows():
        rid = str(row.get(record_id_col, ""))
        if not rid:
            continue

        root = Element("goobi-import")
        data = SubElement(root, "data", type=data_type)

        # --- Standard metadata ---
        _add_meta(data, "Identifier", "CatalogIDDigital", rid)

        # Mapped fields from CSV
        for csv_col, (label, mtype) in fmap.items():
            if csv_col in row and pd.notna(row[csv_col]) and str(row[csv_col]).strip():
                val = str(row[csv_col]).strip()
                # Collections can be multi-valued (semicolon-separated)
                if mtype == "singleDigCollection":
                    for part in val.split(";"):
                        part = part.strip()
                        if part:
                            _add_meta(data, label, mtype, part)
                else:
                    _add_meta(data, label, mtype, val)

        # EDTF date override
        if rid in dates_by_record:
            _add_meta(data, "Erscheinungsjahr", "PublicationYear", dates_by_record[rid])

        # --- Entities as persons/corporates/subjects ---
        record_ents = entities_by_record.get(rid, [])

        for ent in record_ents:
            if ent.entity_type == "PER":
                _add_person(data, ent)
            elif ent.entity_type == "ORG":
                _add_corporate(data, ent)
            else:
                # All other entity types → metadata subjects with GND if available
                val = ent.normalized or ent.text
                attrs = {}
                if ent.gnd_id:
                    attrs["authority"] = "gnd"
                    attrs["authorityURI"] = GND_URI_BASE
                    attrs["valueURI"] = ent.gnd_id
                meta = SubElement(data, "metadata", label="Schlagwort",
                                  type="SubjectTopic", **attrs)
                meta.text = val

        # --- Process block ---
        process = SubElement(root, "process")
        title = SubElement(process, "title")
        title.text = rid
        journal = SubElement(process, "journal", type="info",
                             creator="Debussy")
        journal.text = "Export aus Debussy Kuratierungswerkbank"

        indent(root, space="  ")
        xml_str = tostring(root, encoding="unicode", xml_declaration=False)
        results.append((rid, xml_str))

    return results


def export_goobi_batch(
    df: pd.DataFrame,
    workspace: Workspace,
    record_id_col: str = "record_id",
    field_map: dict | None = None,
) -> str:
    """Export all records as a single multi-record XML string."""
    records = export_goobi_xml(df, workspace, record_id_col, field_map)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<goobi-import-batch>']
    for rid, xml in records:
        parts.append(f"  <!-- Record: {rid} -->")
        # Indent each record
        for line in xml.split("\n"):
            parts.append(f"  {line}")
    parts.append("</goobi-import-batch>")
    return "\n".join(parts)


# --- Helpers ---

def _add_meta(parent: Element, label: str, mtype: str, value: str, **attrs):
    meta = SubElement(parent, "metadata", label=label, type=mtype, **attrs)
    meta.text = value


def _add_person(parent: Element, ent: CuratedEntity):
    """Add a <person> element from a PER entity."""
    name = ent.normalized or ent.text
    # Try to split into first/last name
    parts = name.rsplit(" ", 1)
    if len(parts) == 2:
        first, last = parts[0], parts[1]
    else:
        first, last = "", name

    attrs = {
        "label": "Autor", "role": "Author",
        "firstname": first, "lastname": last,
    }
    if ent.gnd_id:
        attrs["authority"] = "gnd"
        attrs["authorityURI"] = GND_URI_BASE
        attrs["valueURI"] = ent.gnd_id

    SubElement(parent, "person", **attrs)


def _add_corporate(parent: Element, ent: CuratedEntity):
    """Add a <corporate> element from an ORG entity."""
    attrs = {"role": "CorporateArtist", "name": ent.normalized or ent.text}
    if ent.gnd_id:
        attrs["authority"] = "gnd"
        attrs["authorityURI"] = GND_URI_BASE
        attrs["valueURI"] = ent.gnd_id

    SubElement(parent, "corporate", **attrs)
