"""
METS/MODS XML Export (Phase 3) — Standardized metadata interchange.

METS (Metadata Encoding and Transmission Standard) containers with MODS
(Metadata Object Description Schema) descriptive metadata for export to
digital library platforms, institutional repositories, and GLAM systems
that consume METS/MODS.

Includes:
- Bibliographic metadata (title, creator, subject, date)
- NER-extracted entities (persons, places, organizations)
- EDTF-normalized temporal coverage and dates
- GND authority references (persons, places)
- Image technical metadata (if present)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from xml.etree.ElementTree import Element, SubElement, tostring, indent as et_indent
import sys

import pandas as pd

if TYPE_CHECKING:
    from kwb.core.workspace import Workspace

logger = logging.getLogger(__name__)

# Compatibility shim: xml.etree.ElementTree.indent() was added in 3.9
if sys.version_info >= (3, 9):
    _et_indent = et_indent
else:
    def _et_indent(tree: Element, space: str = "  ", level: int = 0) -> None:
        """Recursively indent XML tree for readability (Python < 3.9)."""
        indent_str = "\n" + (level * space)
        if len(tree):
            if not tree.text or not tree.text.strip():
                tree.text = indent_str + space
            if not tree.tail or not tree.tail.strip():
                tree.tail = indent_str
            for child in tree:
                _et_indent(child, space, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = indent_str
        else:
            if level and (not tree.tail or not tree.tail.strip()):
                tree.tail = indent_str


# XML namespaces for METS/MODS
_METS_NS = "http://www.loc.gov/METS/"
_MODS_NS = "http://www.loc.gov/mods/v3"
_XLINK_NS = "http://www.w3.org/1999/xlink"

# Namespace prefixes for QNames
_NSMAP = {
    "mets": _METS_NS,
    "mods": _MODS_NS,
    "xlink": _XLINK_NS,
}


def _elem(tag: str, ns: str | None = None, **attrs) -> Element:
    """Create Element with optional namespace."""
    if ns:
        full_tag = f"{{{ns}}}{tag}"
    else:
        full_tag = tag
    return Element(full_tag, **attrs)


def _subelem(parent: Element, tag: str, ns: str | None = None, **attrs) -> Element:
    """Create SubElement with optional namespace."""
    if ns:
        full_tag = f"{{{ns}}}{tag}"
    else:
        full_tag = tag
    return SubElement(parent, full_tag, **attrs)


def _make_mods_record(
    row: dict[str, Any],
    field_mapping: list,
    id_column: str,
    entities_by_record: dict[str, list],
    dates_by_record: dict[str, list],
    image_by_record: dict[str, dict[str, str]],
) -> Element:
    """Convert a single record to MODS descriptive metadata element."""
    record_id = str(row.get(id_column, ""))

    mods = _elem("mods", ns=_MODS_NS)
    mods.set("xmlns:mods", _MODS_NS)
    mods.set("version", "3.7")

    # Map standard field types to MODS elements
    type_to_mods = {
        "TitleDocMain": "titleInfo",
        "Description": "abstract",
        "Creator": "name",  # Special handling for persons
        "Publisher": "originInfo",
        "DateCreated": "originInfo",
        "DateIssued": "originInfo",
        "Rights": "accessCondition",
        "SubjectTopic": "subject",
        "SubjectGeographic": "subject",
        "SubjectPerson": "subject",
        "SubjectCorporation": "subject",
        "InventoryNumber": "identifier",
        "CatalogIDDigital": "recordInfo",
    }

    # Track which elements have been added (for complex types like originInfo)
    added_sections: set[str] = set()

    # Process field mappings — both regular CSV columns and image.* virtual columns
    # image.* fields come from accepted image analyses (image_by_record), not the CSV row
    img_values = image_by_record.get(record_id, {})
    for fm in field_mapping:
        if fm.is_ignored:
            continue
        col = fm.csv_column

        # Resolve value: image.* fields come from image_by_record, others from row
        if col.startswith("image."):
            val = img_values.get(col, "")
        elif col in row:
            val = row[col]
        else:
            continue

        if pd.isna(val) or str(val).strip() == "":
            continue

        val_str = str(val).strip()
        mods_key = type_to_mods.get(fm.goobi_type, fm.goobi_type)

        # Split repeatable values universally: apply to all field types (P2)
        values = [v.strip() for v in val_str.split(";")] if fm.repeatable else [val_str]

        for v in values:
            if not v:
                continue

            # Title
            if mods_key == "titleInfo":
                title_info = _subelem(mods, "titleInfo", ns=_MODS_NS)
                _subelem(title_info, "title", ns=_MODS_NS).text = v

            # Abstract / Description
            elif mods_key == "abstract":
                _subelem(mods, "abstract", ns=_MODS_NS).text = v

            # Creator / Name — role must contain <roleTerm> children per MODS schema
            elif mods_key == "name":
                name_elem = _subelem(mods, "name", ns=_MODS_NS)
                name_elem.set("type", "personal")
                _subelem(name_elem, "namePart", ns=_MODS_NS).text = v
                role_elem = _subelem(name_elem, "role", ns=_MODS_NS)
                role_term = _subelem(role_elem, "roleTerm", ns=_MODS_NS)
                role_term.set("type", "text")
                role_term.text = fm.goobi_type

            # Origin info (publication info, dates)
            elif mods_key == "originInfo":
                # Reuse existing or create new originInfo
                origin = None
                for child in mods:
                    if child.tag == f"{{{_MODS_NS}}}originInfo":
                        origin = child
                        break
                if origin is None:
                    origin = _subelem(mods, "originInfo", ns=_MODS_NS)

                if fm.goobi_type in ("DateCreated", "DateIssued"):
                    date_elem = _subelem(origin, "dateIssued", ns=_MODS_NS)
                    date_elem.text = v
                else:
                    pub_elem = _subelem(origin, "publisher", ns=_MODS_NS)
                    pub_elem.text = v

            # Subject / Keywords — preserve semantic type
            elif mods_key == "subject":
                subj = _subelem(mods, "subject", ns=_MODS_NS)
                if fm.goobi_type == "SubjectGeographic":
                    sub_child = _subelem(subj, "geographic", ns=_MODS_NS)
                elif fm.goobi_type == "SubjectPerson":
                    # Personal subjects: use nested <name type="personal"><namePart>
                    name_elem = _subelem(subj, "name", ns=_MODS_NS)
                    name_elem.set("type", "personal")
                    sub_child = _subelem(name_elem, "namePart", ns=_MODS_NS)
                elif fm.goobi_type == "SubjectCorporation":
                    # Corporate subjects: use nested <name type="corporate"><namePart>
                    name_elem = _subelem(subj, "name", ns=_MODS_NS)
                    name_elem.set("type", "corporate")
                    sub_child = _subelem(name_elem, "namePart", ns=_MODS_NS)
                else:
                    sub_child = _subelem(subj, "topic", ns=_MODS_NS)
                sub_child.text = v

            # Identifier
            elif mods_key == "identifier":
                ident = _subelem(mods, "identifier", ns=_MODS_NS)
                ident.set("type", fm.goobi_type.lower())
                ident.text = v

            # Record Info / Catalog ID (special handling)
            elif mods_key == "recordInfo":
                ident = _subelem(mods, "identifier", ns=_MODS_NS)
                ident.set("type", "catalog")
                ident.text = v

            # Access condition / Rights
            elif mods_key == "accessCondition":
                acc = _subelem(mods, "accessCondition", ns=_MODS_NS)
                acc.set("type", "use and reproduction")
                acc.text = v

    # Add NER-extracted subjects
    ents = entities_by_record.get(record_id, [])
    if ents:
        # Extract place/geo names — only flag as GND authority if a GND ID is present
        places = [e for e in ents if e["type"] in ("LOC", "GPE")]
        for place in places:
            subj = _subelem(mods, "subject", ns=_MODS_NS)
            if place.get("gnd_id"):
                subj.set("authority", "gnd")
                subj.set("valueURI", f"http://d-nb.info/gnd/{place['gnd_id']}")
            geog = _subelem(subj, "geographic", ns=_MODS_NS)
            geog.text = place.get("name", "")

        # Extract persons
        persons = [e for e in ents if e["type"] == "PER"]
        for person in persons:
            name_elem = _subelem(mods, "name", ns=_MODS_NS)
            name_elem.set("type", "personal")
            if person.get("gnd_id"):
                name_elem.set("authority", "gnd")
                name_elem.set("valueURI", f"http://d-nb.info/gnd/{person['gnd_id']}")
            np = _subelem(name_elem, "namePart", ns=_MODS_NS)
            np.text = person.get("name", "")

        # Extract organizations
        orgs = [e for e in ents if e["type"] == "ORG"]
        for org in orgs:
            name_elem = _subelem(mods, "name", ns=_MODS_NS)
            name_elem.set("type", "corporate")
            if org.get("gnd_id"):
                name_elem.set("authority", "gnd")
                name_elem.set("valueURI", f"http://d-nb.info/gnd/{org['gnd_id']}")
            np = _subelem(name_elem, "namePart", ns=_MODS_NS)
            np.text = org.get("name", "")

    # Add EDTF dates
    dates = dates_by_record.get(record_id, [])
    if dates:
        for edtf_val in dates:
            if not edtf_val:
                continue
            # Use temporal extent for EDTF
            subj = _subelem(mods, "subject", ns=_MODS_NS)
            temporal = _subelem(subj, "temporal", ns=_MODS_NS)
            temporal.set("encoding", "edtf")
            temporal.text = edtf_val

    return mods


def export_mets_mods(
    df: pd.DataFrame,
    workspace: "Workspace",
    *,
    limit: int | None = None,
    profile: Any = None,
) -> str:
    """
    Export DataFrame + workspace data as METS/MODS XML.

    Each record becomes one METS document with MODS descriptive metadata.

    Parameters
    ----------
    df:        Source DataFrame
    workspace: Workspace with field_mapping, entity_reviews, dates
    limit:     Maximum records to export (None = all)
    profile:   Dataset profile with id_column (from ingestion)

    Returns a formatted METS XML string with DOCTYPE declaration.
    """
    # Derive ID column: prefer profile.id_column (from ingestion), then workspace config
    id_col = None
    if profile and hasattr(profile, "id_column") and profile.id_column:
        if profile.id_column in df.columns:
            id_col = profile.id_column
    if not id_col and workspace.id_column and workspace.id_column in df.columns:
        id_col = workspace.id_column
    if not id_col:
        id_col = df.columns[0] if len(df.columns) > 0 else "record_id"
    active_mappings = workspace.active_mappings()

    # Build entity lookup per record — exclude rejected entities
    entities_by_record: dict[str, list] = {}
    for er in workspace.entity_reviews:
        if er.status.value == "rejected":
            continue
        rid = er.record_id or ""
        entities_by_record.setdefault(rid, [])
        entities_by_record[rid].append({
            "name": er.gnd_preferred or er.text,
            "type": er.entity_type,
            "gnd_id": er.gnd_id,
        })

    # Build date lookup per record
    dates_by_record: dict[str, list] = {}
    for cd in workspace.dates:
        if cd.edtf:
            rid = cd.record_id or ""
            dates_by_record.setdefault(rid, [])
            dates_by_record[rid].append(cd.edtf)

    # Build accepted image-analysis lookup per record
    image_by_record: dict[str, dict[str, str]] = {}
    for img in workspace.image_analyses:
        if img.review_status.value != "accepted" or not img.record_id:
            continue
        payload = img.result if isinstance(img.result, dict) else {}
        image_by_record.setdefault(img.record_id, {})
        for key, value in payload.items():
            if isinstance(value, list):
                rendered = "; ".join(str(x) for x in value if str(x).strip())
            else:
                rendered = str(value)
            if rendered.strip():
                field_key = f"image.{key}"
                # Accumulate multiple values from different analyses (P1)
                if field_key in image_by_record[img.record_id]:
                    image_by_record[img.record_id][field_key] += "; " + rendered
                else:
                    image_by_record[img.record_id][field_key] = rendered

    # Root element: METS document
    root = _elem("mets", ns=_METS_NS)
    root.set("xmlns:mets", _METS_NS)
    root.set("xmlns:mods", _MODS_NS)
    root.set("xmlns:xlink", _XLINK_NS)
    root.set("OBJID", "debussy-export")

    # METS header — CREATEDATE must reflect actual export time for valid provenance
    mets_hdr = _subelem(root, "metsHdr", ns=_METS_NS)
    create_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    mets_hdr.set("CREATEDATE", create_date)
    mets_hdr.set("RECORDSTATUS", "Complete")

    # Descriptive metadata section (dmdSec)
    rows = df.head(limit) if limit is not None else df
    for idx, (_, row) in enumerate(rows.iterrows()):
        record_id = str(row.get(id_col, ""))
        dmd_id = f"dmd{idx}"

        dmd_sec = _subelem(root, "dmdSec", ns=_METS_NS)
        dmd_sec.set("ID", dmd_id)

        md_wrap = _subelem(dmd_sec, "mdWrap", ns=_METS_NS)
        md_wrap.set("MDTYPE", "MODS")

        xml_data = _subelem(md_wrap, "xmlData", ns=_METS_NS)

        # Create MODS record
        mods = _make_mods_record(
            row.to_dict(), active_mappings, id_col,
            entities_by_record, dates_by_record, image_by_record,
        )
        xml_data.append(mods)

    # File section (minimal for metadata-only export)
    file_sec = _subelem(root, "fileSec", ns=_METS_NS)
    file_grp = _subelem(file_sec, "fileGrp", ns=_METS_NS)
    file_grp.set("USE", "metadata")

    # Structural map: map records to their dmdSec
    struct_map = _subelem(root, "structMap", ns=_METS_NS)
    struct_map.set("TYPE", "physical")
    div_root = _subelem(struct_map, "div", ns=_METS_NS)
    div_root.set("TYPE", "document")
    div_root.set("LABEL", "Debussy Export")

    for idx, (_, row) in enumerate(rows.iterrows()):
        record_id = str(row.get(id_col, ""))
        dmd_id = f"dmd{idx}"
        div_rec = _subelem(div_root, "div", ns=_METS_NS)
        div_rec.set("TYPE", "record")
        div_rec.set("LABEL", record_id)
        div_rec.set("DMDID", dmd_id)

    # Pretty-print
    _et_indent(root)
    xml_str = tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'


def export_mets_mods_bytes(
    df: pd.DataFrame,
    workspace: "Workspace",
    **kwargs,
) -> bytes:
    """Return METS/MODS as UTF-8 bytes."""
    return export_mets_mods(df, workspace, **kwargs).encode("utf-8")
