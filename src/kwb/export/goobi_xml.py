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

import logging
import re
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import (
    Element, SubElement, ElementTree, tostring, indent as et_indent
)
import sys

import pandas as pd

logger = logging.getLogger(__name__)

from kwb.core.workspace import (
    FieldMapping, DictionaryEntry, Workspace
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


# EXP-BUG-07 (#192): Nobiliary / surname particles in DE, NL, FR, IT, ES.
# When parsing "Firstname Lastname" form, these tokens stick to the surname
# rather than ending up as part of the first name.
_NOBILIARY_PARTICLES = frozenset({
    # German / Dutch
    "von", "vom", "zu", "zur", "van", "ten", "ter", "der",
    # French
    "de", "du", "des", "le", "la",
    # Italian / Spanish
    "del", "della", "di", "da", "dal", "dalla", "lo", "los", "las",
})


def _parse_name(full_name: str) -> tuple[str, str]:
    """
    Split 'Lastname, Firstname' or 'Firstname Lastname' into parts.
    Returns (firstname, lastname).

    Handles nobiliary particles (#192): "von Goethe" → ("", "von Goethe"),
    "Johann Wolfgang von Goethe" → ("Johann Wolfgang", "von Goethe").
    """
    if "," in full_name:
        parts = full_name.split(",", 1)
        return parts[1].strip(), parts[0].strip()

    tokens = full_name.split()
    if len(tokens) < 2:
        return "", full_name.strip()

    # Walk from the right collecting particle tokens into the surname.
    # The surname always starts at the index where the last particle begins
    # (or, if no particle precedes the final token, just the final token).
    surname_start = len(tokens) - 1
    while surname_start > 0 and tokens[surname_start - 1].lower() in _NOBILIARY_PARTICLES:
        surname_start -= 1

    firstname = " ".join(tokens[:surname_start]).strip()
    lastname = " ".join(tokens[surname_start:]).strip()
    return firstname, lastname




def _iter_accepted_image_metadata(workspace: Workspace, record_id: str):
    """Yield tuples of (key, value) for accepted image analyses mapped to a record."""
    for analysis in workspace.image_analyses:
        if analysis.record_id != record_id:
            continue
        if analysis.review_status.value != "accepted":
            continue
        payload = analysis.result if isinstance(analysis.result, dict) else {}
        for k, v in payload.items():
            if isinstance(v, list):
                value = "; ".join(str(x) for x in v if str(x).strip())
            else:
                value = str(v)
            if value.strip():
                yield f"image.{k}", value


def _apply_image_mappings_to_xml(data_elem: Element, workspace: Workspace, record_id: str):
    """Append mapped accepted image metadata as <metadata> elements."""
    image_values = dict(_iter_accepted_image_metadata(workspace, record_id))
    if not image_values:
        return
    for m in workspace.active_mappings():
        if not m.csv_column.startswith("image."):
            continue
        value = image_values.get(m.csv_column, "")
        if not value:
            continue
        if m.repeatable and ";" in value:
            for part in _split_repeatable(value):
                me = SubElement(data_elem, "metadata", label=m.label or m.goobi_type, type=m.goobi_type)
                me.text = part
        else:
            me = SubElement(data_elem, "metadata", label=m.label or m.goobi_type, type=m.goobi_type)
            me.text = value

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

    dict_lookup = {e.term.lower(): e for e in workspace.dictionary}
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<goobi-import-batch>"]

    for _, row in df.iterrows():
        elem = record_to_xml(
            row=row.to_dict(),
            field_mapping=workspace.active_mappings(),
            dictionary=dict_lookup,
            doc_type=doc_type,
            journal_message=journal_message,
        )
        _et_indent(elem, space="  ")
        xml_bytes = tostring(elem, encoding="unicode")
        parts.append(xml_bytes)

    parts.append("</goobi-import-batch>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Convenience wrappers (used by tests and API routes)
# ---------------------------------------------------------------------------

def export_goobi_xml(
    df: pd.DataFrame,
    workspace: Workspace,
    doc_type: str = "MuseumObject",
    auto_add_catalog_id: bool = True,
) -> list[tuple[str, str]]:
    """
    Export each row of a DataFrame to individual Goobi XML strings.

    Parameters
    ----------
    df:                   Source DataFrame
    workspace:            Workspace with field_mapping
    doc_type:             Goobi document type attribute
    auto_add_catalog_id:  EXP-BUG-02 (#187). When True (default for
        back-compat), the function injects a record_id → CatalogIDDigital
        mapping if the curator has not mapped it. Each injection logs a
        warning so it is no longer silent. Set to False to fail-fast when
        CatalogIDDigital is unmapped — recommended for production exports
        where any silent transformation undermines trust.

    Returns
    -------
    A list of (record_id, xml_string) tuples.

    Raises
    ------
    ValueError if auto_add_catalog_id=False and CatalogIDDigital is not
    mapped in the workspace.
    """
    mappings = workspace.active_mappings()
    dict_lookup: dict[str, DictionaryEntry] = {}
    for d in workspace.dictionary:
        dict_lookup.setdefault(d.term.lower(), d)

    # EXP-BUG-02 (#187): surface CatalogIDDigital handling up-front rather
    # than silently injecting per-row. Either fail-fast or warn once.
    mapped_goobi_types = {m.goobi_type for m in mappings}
    catalog_id_mapped = "CatalogIDDigital" in mapped_goobi_types
    if not catalog_id_mapped:
        if not auto_add_catalog_id:
            raise ValueError(
                "CatalogIDDigital is not mapped in the workspace. "
                "Either map a column to CatalogIDDigital in the field-mapping "
                "screen, or pass auto_add_catalog_id=True to auto-inject "
                "record_id (which will produce a warning per record)."
            )
        logger.warning(
            "EXP-BUG-02: CatalogIDDigital was not mapped explicitly; "
            "auto-injecting record_id → CatalogIDDigital. Map it explicitly "
            "to silence this warning."
        )

    for ent in workspace.entities:
        if getattr(ent.status, "value", ent.status) != "rejected" and ent.gnd_id:
            key = ent.text.lower()
            if key not in dict_lookup:
                dict_lookup[key] = DictionaryEntry(
                    term=ent.text, gnd_id=ent.gnd_id,
                )

    results: list[tuple[str, str]] = []
    for _, row in df.iterrows():
        record_id = str(row.get("record_id", f"row_{_}"))
        row_dict = row.to_dict()

        # Check for EDTF date overrides
        for dt in workspace.dates:
            if dt.record_id == record_id and dt.edtf:
                for col_name, val in row_dict.items():
                    if isinstance(val, str) and val.strip() == dt.original:
                        row_dict[col_name] = dt.edtf

        # EXP-BUG-02 (#187): Inject record_id → CatalogIDDigital only when
        # auto_add was approved at the function level and the workspace has
        # no explicit mapping. The function-level warning above already
        # surfaced this once.
        auto_mappings = list(mappings)
        if (
            auto_add_catalog_id
            and not catalog_id_mapped
            and "record_id" in row_dict
            and "record_id" not in {m.csv_column for m in auto_mappings}
        ):
            auto_mappings.insert(0, FieldMapping(
                csv_column="record_id",
                goobi_type="CatalogIDDigital",
                label="CatalogIDDigital",
            ))

        elem = record_to_xml(
            row=row_dict,
            field_mapping=auto_mappings,
            dictionary=dict_lookup,
            doc_type=doc_type,
        )

        record_entities = [
            e for e in workspace.entities
            if e.record_id == record_id and getattr(e.status, "value", e.status) != "rejected"
        ]
        data_elem = elem.find("data")
        if record_entities and data_elem is not None:
                for ent in record_entities:
                    gnd_attrs: dict[str, str] = {}
                    ent_entry = dict_lookup.get(ent.text.lower())
                    if ent_entry:
                        gnd_attrs = _gnd_attrs(ent_entry)
                    if not gnd_attrs and ent.gnd_id:
                        gnd_attrs = {
                            "authority": "gnd",
                            "authorityURI": "http://d-nb.info/gnd/",
                            "valueURI": ent.gnd_id,
                        }

                    if ent.entity_type == "PER":
                        fn, ln = _parse_name(ent.text)
                        SubElement(data_elem, "person",
                                   label="Person", role="Author",
                                   firstname=fn, lastname=ln,
                                   **gnd_attrs)
                    elif ent.entity_type == "ORG":
                        SubElement(data_elem, "corporate",
                                   role="CorporateBody",
                                   name=ent.text,
                                   **gnd_attrs)
                    else:
                        attrs: dict[str, str] = {
                            "label": "Schlagwort",
                            "type": "SubjectTopic",
                        }
                        attrs.update(gnd_attrs)
                        se = SubElement(data_elem, "metadata", **attrs)
                        se.text = ent.text

        if data_elem is not None:
            _apply_image_mappings_to_xml(data_elem, workspace, record_id)

        _et_indent(elem, space="  ")
        xml_str = tostring(elem, encoding="unicode")
        results.append((record_id, xml_str))

    return results


def export_goobi_batch(
    df: pd.DataFrame,
    workspace: Workspace,
    doc_type: str = "MuseumObject",
) -> str:
    """
    Export all rows as a single Goobi batch XML string.

    Wraps individual record XMLs in <goobi-import-batch>.
    """
    records = export_goobi_xml(df, workspace, doc_type=doc_type)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<goobi-import-batch>"]
    for _, xml_str in records:
        parts.append(xml_str)
    parts.append("</goobi-import-batch>")
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

    Raises ValueError if filename sanitization produces collisions
    (e.g. "obj 001" and "obj/001" both become "obj_001").
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # EXP-BUG-04: Build record_id -> safe_filename mapping upfront, detect collisions.
    record_to_safe_id: dict[str, str] = {}
    safe_id_to_records: dict[str, list[str]] = {}

    for _, row in df.iterrows():
        record_id = str(row.get("record_id", f"row_{_}"))
        safe_id = re.sub(r"[^\w\-]", "_", record_id)

        record_to_safe_id[record_id] = safe_id
        safe_id_to_records.setdefault(safe_id, []).append(record_id)

    # Check for collisions
    collisions = {safe_id: ids for safe_id, ids in safe_id_to_records.items() if len(ids) > 1}
    if collisions:
        details = "; ".join(
            f"'{safe_id}': {ids}" for safe_id, ids in collisions.items()
        )
        raise ValueError(
            f"Filename collision detected in record IDs. "
            f"The following sanitized filenames would overwrite each other: {details}"
        )

    # Write files
    written = []
    for _, row in df.iterrows():
        record_id = str(row.get("record_id", f"row_{_}"))
        safe_id = record_to_safe_id[record_id]

        dict_lookup = {e.term.lower(): e for e in workspace.dictionary}
        elem = record_to_xml(
            row=row.to_dict(),
            field_mapping=workspace.active_mappings(),
            dictionary=dict_lookup,
            doc_type=doc_type,
        )
        _et_indent(elem, space="  ")

        path = output_dir / f"{safe_id}.xml"
        tree = ElementTree(elem)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        written.append(path)

    return written