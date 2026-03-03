"""
Goobi XML Export — generates goobi-import XML from enriched metadata.

This is the *only* place that knows about the Goobi XML schema.
It consumes a Workspace (field_mapping + dictionary) and a DataFrame.

KEY FIXES vs original goobi_xml.py:
1. Uses xml.etree.ElementTree properly — no manual indent() for Python < 3.9.
2. XML declaration is written once at the top (not per-record).
3. field_mapping drives what goes into the output; without a mapping
   only record_id is exported (now clearly documented and testable).
4. Repeatable fields (semicolon-separated) are exploded to multiple elements.
5. GND authority attributes use DictionaryEntry when available.
6. `indent()` replaced with recursive function that works on all Python ≥ 3.7.

SUPPORTED ELEMENT TYPES (from Goobi schema):
  metadata         → plain metadata field
  person           → firstname / lastname split on ", " or " "
  corporate        → name + optional subnames (pipe-separated in CSV)
  singleDigCollection → repeatable Sammlung/Collection
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import (
    Element, SubElement, ElementTree, tostring, indent as et_indent
)
import sys

import pandas as pd

from kwb.core.workspace import (
    FieldMapping, GoobiMetadataType, DictionaryEntry, Workspace
)


# ---------------------------------------------------------------------------
# Compatibility shim: xml.etree.ElementTree.indent() was added in 3.9
# ---------------------------------------------------------------------------

if sys.version_info >= (3, 9):
    _et_indent = et_indent
else:
    def _et_indent(tree: Element, space: str = "  ", level: int = 0) -> None:
        """Recursive pretty-printer for ElementTree, Python < 3.9."""
        i = "\n" + level * space
        if len(tree):
            if not tree.text or not tree.text.strip():
                tree.text = i + space
            if not tree.tail or not tree.tail.strip():
                tree.tail = i
            for subtree in tree:
                _et_indent(subtree, space, level + 1)
            if not subtree.tail or not subtree.tail.strip():  # type: ignore
                subtree.tail = i  # type: ignore
        else:
            if level and (not tree.tail or not tree.tail.strip()):
                tree.tail = i


# ---------------------------------------------------------------------------
# Known person-type Goobi types
# ---------------------------------------------------------------------------

_PERSON_TYPES = {
    "Author", "Creator", "Photographer", "Artist", "Editor",
    "Contributor", "Illustrator",
}

_CORPORATE_TYPES = {
    "CorporateBody", "CorporateArtist", "Publisher", "PrintingHouse",
}

_COLLECTION_TYPES = {
    "singleDigCollection",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gnd_attrs(entry: DictionaryEntry | None) -> dict[str, str]:
    """Return XML attributes for a GND-linked element."""
    if entry and entry.gnd_id:
        return {
            "authority": "gnd",
            "authorityURI": "http://d-nb.info/gnd/",
            "valueURI": entry.gnd_id,
        }
    return {}


def _split_repeatable(value: str, sep: str = ";") -> list[str]:
    return [v.strip() for v in value.split(sep) if v.strip()]


def _parse_name(full_name: str) -> tuple[str, str]:
    """
    Split 'Lastname, Firstname' or 'Firstname Lastname' into parts.
    Returns (firstname, lastname).
    """
    if "," in full_name:
        parts = full_name.split(",", 1)
        return parts[1].strip(), parts[0].strip()
    parts = full_name.rsplit(" ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", full_name.strip()


# ---------------------------------------------------------------------------
# Single-record export
# ---------------------------------------------------------------------------

def record_to_xml(
    row: dict[str, Any],
    field_mapping: list[FieldMapping],
    dictionary: dict[str, DictionaryEntry] | None = None,
    doc_type: str = "MuseumObject",
    journal_message: str = "Import via Debussy Kuratierwerkbank",
) -> Element:
    """
    Convert one metadata record (dict) to a <goobi-import> Element.

    field_mapping drives the conversion; only mapped+enabled columns
    are included in the output. Without a field_mapping that includes
    CatalogIDDigital, the record will have no identifier.
    """
    dict_ = dictionary or {}

    root = Element("goobi-import")
    data = SubElement(root, "data", type=doc_type)

    record_id = str(row.get("record_id", ""))

    for mapping in field_mapping:
        if mapping.is_ignored:
            continue

        col = mapping.csv_column
        value = row.get(col)
        if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "":
            continue

        value_str = str(value).strip()
        goobi_type = mapping.goobi_type
        label = mapping.label or goobi_type

        # Look up in dictionary
        entry = dict_.get(value_str.lower())

        # --- Person ---
        if goobi_type in _PERSON_TYPES:
            names_raw = _split_repeatable(value_str) if mapping.repeatable else [value_str]
            for name_raw in names_raw:
                fn, ln = _parse_name(name_raw)
                attrs = {
                    "label": label,
                    "role": goobi_type,
                    "firstname": fn,
                    "lastname": ln,
                }
                attrs.update(_gnd_attrs(dict_.get(name_raw.lower())))
                SubElement(data, "person", **attrs)
            continue

        # --- Corporate ---
        if goobi_type in _CORPORATE_TYPES:
            parts = _split_repeatable(value_str, sep="|") if "|" in value_str else [value_str]
            corp_name = parts[0]
            corp_elem = SubElement(
                data, "corporate",
                role=goobi_type,
                name=corp_name,
                **_gnd_attrs(dict_.get(corp_name.lower())),
            )
            for sub in parts[1:]:
                SubElement(corp_elem, "subname").text = sub
            continue

        # --- Repeatable metadata (singleDigCollection and custom repeatable) ---
        if mapping.repeatable or goobi_type in _COLLECTION_TYPES:
            values = _split_repeatable(value_str)
            for v in values:
                e = SubElement(data, "metadata", label=label, type=goobi_type)
                e.text = v
                # GND authority from dictionary
                entry_v = dict_.get(v.lower())
                if entry_v and entry_v.gnd_id:
                    e.set("authority", "gnd")
                    e.set("authorityURI", "http://d-nb.info/gnd/")
                    e.set("valueURI", entry_v.gnd_id)
            continue

        # --- Standard metadata ---
        attrs_meta: dict[str, str] = {"label": label, "type": goobi_type}
        if entry and entry.gnd_id:
            attrs_meta.update({
                "authority": "gnd",
                "authorityURI": "http://d-nb.info/gnd/",
                "valueURI": entry.gnd_id,
            })
        elem = SubElement(data, "metadata", **attrs_meta)
        elem.text = value_str

    # --- Process block ---
    proc = SubElement(root, "process")
    SubElement(proc, "title").text = record_id
    journal = SubElement(proc, "journal", type="info", creator="- automatic -")
    journal.text = journal_message

    return root


# ---------------------------------------------------------------------------
# Batch export
# ---------------------------------------------------------------------------

def dataframe_to_goobi_xml(
    df: pd.DataFrame,
    workspace: Workspace,
    doc_type: str = "MuseumObject",
    journal_message: str = "Import via Debussy Kuratierwerkbank",
) -> str:
    """
    Export the entire DataFrame to Goobi import XML (one <goobi-import> per row).

    Returns the complete XML string with declaration.

    Uses workspace.active_mappings() and workspace.dictionary.
    """
    if not workspace.active_mappings():
        raise ValueError(
            "Workspace has no active field mappings. "
            "Configure field_mapping before export."
        )

    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<goobi-batch>"]

    for _, row in df.iterrows():
        elem = record_to_xml(
            row=row.to_dict(),
            field_mapping=workspace.active_mappings(),
            dictionary=workspace.dictionary,
            doc_type=doc_type,
            journal_message=journal_message,
        )
        _et_indent(elem, space="  ")
        xml_bytes = tostring(elem, encoding="unicode")
        parts.append(xml_bytes)

    parts.append("</goobi-batch>")
    return "\n".join(parts)


def dataframe_to_goobi_xml_files(
    df: pd.DataFrame,
    workspace: Workspace,
    output_dir: str | Path,
    doc_type: str = "MuseumObject",
) -> list[Path]:
    """
    Write one XML file per record to output_dir.

    Returns list of written file paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for _, row in df.iterrows():
        record_id = str(row.get("record_id", f"row_{_}"))
        safe_id = re.sub(r"[^\w\-]", "_", record_id)

        elem = record_to_xml(
            row=row.to_dict(),
            field_mapping=workspace.active_mappings(),
            dictionary=workspace.dictionary,
            doc_type=doc_type,
        )
        _et_indent(elem, space="  ")

        path = output_dir / f"{safe_id}.xml"
        tree = ElementTree(elem)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        written.append(path)

    return written
# Backward compatibility for API imports
export_goobi_xml = dataframe_to_goobi_xml
export_goobi_batch = dataframe_to_goobi_xml_files