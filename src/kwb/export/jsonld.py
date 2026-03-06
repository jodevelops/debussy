"""
JSON-LD Export (F35) — Linked Open Data Export.

Serialisiert Workspace-Daten und Records als JSON-LD nach Schema.org/CIDOC-CRM.
Geeignet für die Veröffentlichung als Linked Open Data.

Verwendet:
- schema:CreativeWork für Sammlungsobjekte
- schema:Person / schema:Place für Entitäten
- schema:Event für Ereignisse
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from kwb.core.workspace import Workspace

logger = logging.getLogger(__name__)

# JSON-LD Context
_CONTEXT = {
    "@vocab": "https://schema.org/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "edm": "http://www.europeana.eu/schemas/edm/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "gnd": "https://d-nb.info/gnd/",
    "wikidata": "https://www.wikidata.org/wiki/",
    "edtf": "http://id.loc.gov/datatypes/edtf",
    "identifier": "dc:identifier",
    "subject": "dc:subject",
    "dateCreated": "dcterms:created",
    "temporal": "dcterms:temporal",
}

# Map entity types to schema.org types
_ENTITY_TYPE_MAP = {
    "PER": "Person",
    "ORG": "Organization",
    "LOC": "Place",
    "GPE": "Place",
    "FAC": "LandmarksOrHistoricalBuildings",
    "EVT": "Event",
    "WRK": "CreativeWork",
    "DAT": "DateTime",
    "ETH": "Audience",
    "CON": "DefinedTerm",
}


def _make_entity_node(entity_review) -> dict[str, Any]:
    """Convert an EntityReview to a JSON-LD node."""
    schema_type = _ENTITY_TYPE_MAP.get(entity_review.entity_type, "Thing")
    node: dict[str, Any] = {
        "@type": schema_type,
        "name": entity_review.text,
    }
    if entity_review.gnd_id:
        node["@id"] = f"gnd:{entity_review.gnd_id}"
        node["sameAs"] = f"https://d-nb.info/gnd/{entity_review.gnd_id}"
    if entity_review.gnd_preferred and entity_review.gnd_preferred != entity_review.text:
        node["alternateName"] = entity_review.text
        node["name"] = entity_review.gnd_preferred
    if entity_review.confidence:
        node["_confidence"] = round(entity_review.confidence, 3)
    return node


def _make_record_node(
    row: pd.Series,
    id_column: str,
    field_mapping: list,
    entities_by_record: dict[str, list],
    dates_by_record: dict[str, list],
    image_by_record: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Convert a single DataFrame row to a JSON-LD CreativeWork node."""
    record_id = str(row.get(id_column, ""))
    node: dict[str, Any] = {
        "@type": "CreativeWork",
        "identifier": record_id,
    }

    # Map columns via FieldMapping
    type_to_schema = {
        "TitleDocMain": "name",
        "Description": "description",
        "Creator": "creator",
        "Publisher": "publisher",
        "DateCreated": "dateCreated",
        "DateIssued": "datePublished",
        "Rights": "license",
        "SubjectTopic": "keywords",
        "SubjectGeographic": "contentLocation",
        "SubjectPerson": "mentions",
        "InventoryNumber": "identifier",
        "CatalogIDDigital": "@id",
    }

    for fm in field_mapping:
        if fm.is_ignored:
            continue
        col = fm.csv_column
        if col not in row.index:
            continue
        val = row[col]
        if pd.isna(val) or str(val).strip() == "":
            continue
        schema_key = type_to_schema.get(fm.goobi_type, fm.goobi_type)
        str_val = str(val).strip()
        if schema_key == "@id":
            node["@id"] = f"urn:glam:{str_val}"
        elif fm.repeatable and ";" in str_val:
            node[schema_key] = [v.strip() for v in str_val.split(";") if v.strip()]
        else:
            node[schema_key] = str_val

    # Add NER entities
    ents = entities_by_record.get(record_id, [])
    if ents:
        # Group by type
        persons = [e for e in ents if e["type"] in ("PER",)]
        places = [e for e in ents if e["type"] in ("LOC", "GPE")]
        orgs = [e for e in ents if e["type"] in ("ORG",)]
        if persons:
            node["mentions"] = persons if len(persons) > 1 else persons[0]
        if places:
            node["contentLocation"] = places if len(places) > 1 else places[0]
        if orgs:
            node["accountablePerson"] = orgs if len(orgs) > 1 else orgs[0]

    # Add EDTF dates
    dates = dates_by_record.get(record_id, [])
    if dates:
        node["temporal"] = [{"@type": "edtf", "@value": d} for d in dates if d]

    # Add accepted image analysis values via field mapping (csv_column = image.*)
    img_vals = image_by_record.get(record_id, {})
    for fm in field_mapping:
        if fm.is_ignored or not fm.csv_column.startswith("image."):
            continue
        val = img_vals.get(fm.csv_column, "")
        if not val:
            continue
        schema_key = type_to_schema.get(fm.goobi_type, fm.goobi_type)
        if fm.repeatable and ";" in val:
            node[schema_key] = [v.strip() for v in val.split(";") if v.strip()]
        else:
            node[schema_key] = val

    return node


def export_jsonld(
    df: pd.DataFrame,
    workspace: "Workspace",
    *,
    base_url: str = "https://example.org/collection/",
    limit: int | None = None,
) -> str:
    """
    Export DataFrame + workspace data as a JSON-LD document.

    Parameters
    ----------
    df:        Source DataFrame
    workspace: Workspace with field_mapping, entity_reviews, dates
    base_url:  Base URI for record identifiers
    limit:     Maximum records to export (None = all)

    Returns a formatted JSON-LD string.
    """
    id_col = workspace.id_column or (df.columns[0] if len(df.columns) > 0 else "record_id")
    active_mappings = workspace.active_mappings()

    # Build entity lookup per record
    entities_by_record: dict[str, list] = {}
    for er in workspace.entity_reviews:
        rid = er.record_id or ""
        entities_by_record.setdefault(rid, [])
        entities_by_record[rid].append({
            "@type": _ENTITY_TYPE_MAP.get(er.entity_type, "Thing"),
            "name": er.gnd_preferred or er.text,
            "type": er.entity_type,
            **({"sameAs": f"https://d-nb.info/gnd/{er.gnd_id}"} if er.gnd_id else {}),
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
                image_by_record[img.record_id][f"image.{key}"] = rendered

    # Build record nodes
    rows = df.head(limit) if limit else df
    items = []
    for _, row in rows.iterrows():
        node = _make_record_node(
            row, id_col, active_mappings,
            entities_by_record, dates_by_record, image_by_record,
        )
        record_id = str(row.get(id_col, ""))
        if "@id" not in node:
            node["@id"] = f"{base_url}{record_id}"
        items.append(node)

    # Build authority entities from dictionary
    authority_graph = []
    for entry in workspace.dictionary:
        if not entry.has_authority:
            continue
        anode: dict[str, Any] = {
            "@type": "DefinedTerm",
            "name": entry.gnd_preferred or entry.term,
        }
        if entry.gnd_id:
            anode["@id"] = f"gnd:{entry.gnd_id}"
            anode["sameAs"] = f"https://d-nb.info/gnd/{entry.gnd_id}"
        if entry.wikidata_id:
            anode["sameAs"] = [
                f"https://d-nb.info/gnd/{entry.gnd_id}" if entry.gnd_id else None,
                f"https://www.wikidata.org/wiki/{entry.wikidata_id}",
            ]
            anode["sameAs"] = [s for s in anode["sameAs"] if s]
        authority_graph.append(anode)

    doc: dict[str, Any] = {
        "@context": _CONTEXT,
        "@graph": items + authority_graph,
    }

    return json.dumps(doc, ensure_ascii=False, indent=2)


def export_jsonld_bytes(
    df: pd.DataFrame,
    workspace: "Workspace",
    **kwargs,
) -> bytes:
    """Return JSON-LD as UTF-8 bytes."""
    return export_jsonld(df, workspace, **kwargs).encode("utf-8")
