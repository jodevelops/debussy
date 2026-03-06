"""
CSV Export (F34) — bereinigter Export mit NER + EDTF Anreicherungen.

Exportiert einen Datensatz als CSV mit:
- Original-Spalten (optional gefiltert via FieldMapping)
- NER-Entitäten als zusätzliche Spalten (ner_persons, ner_places, …)
- EDTF-normalisierte Datumsangaben (edtf_* Spalten)
- GND-IDs aus dem Workspace-Wörterbuch
"""
from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from kwb.core.workspace import Workspace

logger = logging.getLogger(__name__)

# Entity types to export as separate columns
_ENTITY_COLS = {
    "PER": "ner_persons",
    "ORG": "ner_organisations",
    "LOC": "ner_places",
    "GPE": "ner_geo_political",
    "FAC": "ner_buildings",
    "EVT": "ner_events",
    "WRK": "ner_works",
    "DAT": "ner_dates_raw",
    "ETH": "ner_ethnic_groups",
    "CON": "ner_concepts",
}


def export_enriched_csv(
    df: pd.DataFrame,
    workspace: "Workspace",
    *,
    include_ner: bool = True,
    include_edtf: bool = True,
    include_gnd: bool = True,
    include_image_review: bool = True,
    id_column: str = "record_id",
    separator: str = "; ",
) -> str:
    """
    Export a DataFrame enriched with NER, EDTF and GND data from the workspace.

    Returns a UTF-8 encoded CSV string.

    Parameters
    ----------
    df:
        Source DataFrame.
    workspace:
        Workspace with entity_reviews, dates, and dictionary.
    include_ner:
        Add ner_* columns grouped by entity type.
    include_edtf:
        Add edtf_<column> for each date column that was normalized.
    include_gnd:
        Add gnd_id column from workspace dictionary matches.
    id_column:
        Column that links records to workspace entities.
    separator:
        Separator for multi-value cells (default "; ").
    """
    out = df.copy()

    # ------------------------------------------------------------------
    # NER columns — one column per entity type, per record
    # ------------------------------------------------------------------
    if include_ner and workspace.entity_reviews:
        # Build per-record, per-type dict
        ner_by_record: dict[str, dict[str, list[str]]] = {}
        for er in workspace.entity_reviews:
            rid = er.record_id or "__global__"
            ner_by_record.setdefault(rid, {})
            etype = er.entity_type
            col = _ENTITY_COLS.get(etype)
            if col:
                ner_by_record[rid].setdefault(col, [])
                # Use GND preferred name if available, else raw text
                label = er.gnd_preferred if er.gnd_preferred else er.text
                if label not in ner_by_record[rid][col]:
                    ner_by_record[rid][col].append(label)

        for col in _ENTITY_COLS.values():
            if id_column in out.columns:
                out[col] = out[id_column].astype(str).map(
                    lambda rid: separator.join(
                        ner_by_record.get(rid, {}).get(col, [])
                        or ner_by_record.get("__global__", {}).get(col, [])
                    )
                )
            else:
                out[col] = ""

    # ------------------------------------------------------------------
    # EDTF columns — per-record, per original-column
    # ------------------------------------------------------------------
    if include_edtf and workspace.dates:
        # Group by (column, record_id) → edtf value
        edtf_map: dict[str, dict[str, str]] = {}  # {column: {record_id: edtf}}
        for cd in workspace.dates:
            col = cd.column or "__date__"
            edtf_map.setdefault(col, {})
            if cd.edtf and cd.record_id:
                edtf_map[col][cd.record_id] = cd.edtf

        for orig_col, record_edtf in edtf_map.items():
            new_col = f"edtf_{orig_col}"
            if id_column in out.columns and record_edtf:
                out[new_col] = out[id_column].astype(str).map(
                    lambda rid: record_edtf.get(rid, "")
                )
            elif orig_col in out.columns and record_edtf:
                # Try to match via original value
                orig_to_edtf = {cd.original: cd.edtf for cd in workspace.dates if cd.column == orig_col}
                out[new_col] = out[orig_col].astype(str).map(
                    lambda v: orig_to_edtf.get(v, "")
                )
            else:
                out[new_col] = ""

    # ------------------------------------------------------------------
    # Accepted image analysis columns (mapped via field_mapping image.*)
    # ------------------------------------------------------------------
    if include_image_review and workspace.image_analyses:
        image_rows: dict[str, dict[str, str]] = {}
        for img in workspace.image_analyses:
            if img.review_status.value != "accepted":
                continue
            rid = img.record_id
            if not rid:
                continue
            payload = img.result if isinstance(img.result, dict) else {}
            image_rows.setdefault(rid, {})
            image_rows[rid]["image_review_status"] = img.review_status.value
            image_rows[rid]["image_review_comment"] = img.review_comment
            image_rows[rid]["image_reviewer"] = img.reviewer
            for k, v in payload.items():
                col_name = f"image_{k}"
                if isinstance(v, list):
                    rendered = separator.join(str(x) for x in v if str(x).strip())
                else:
                    rendered = str(v)
                if rendered.strip():
                    image_rows[rid][col_name] = rendered

        image_cols = sorted({k for row in image_rows.values() for k in row.keys()})
        for col in image_cols:
            if id_column in out.columns:
                out[col] = out[id_column].astype(str).map(lambda rid: image_rows.get(rid, {}).get(col, ""))
            else:
                out[col] = ""

    # ------------------------------------------------------------------
    # GND columns — add gnd_id / gnd_preferred for known terms
    # ------------------------------------------------------------------
    if include_gnd and workspace.dictionary:
        term_to_gnd: dict[str, str] = {
            e.term.lower(): e.gnd_id
            for e in workspace.dictionary
            if e.gnd_id
        }
        if term_to_gnd:
            # Only add if NER columns exist — map preferred terms to GND IDs
            if "ner_persons" in out.columns:
                def _map_gnd(cell: str) -> str:
                    if not cell:
                        return ""
                    ids = []
                    for term in cell.split(separator.strip()):
                        t = term.strip()
                        gnd = term_to_gnd.get(t.lower(), "")
                        if gnd:
                            ids.append(gnd)
                    return separator.join(ids)

                out["gnd_ids"] = out["ner_persons"].map(_map_gnd)

    # ------------------------------------------------------------------
    # Serialise to CSV string
    # ------------------------------------------------------------------
    buf = io.StringIO()
    out.to_csv(buf, index=False, encoding="utf-8")
    return buf.getvalue()


def export_enriched_csv_bytes(
    df: pd.DataFrame,
    workspace: "Workspace",
    **kwargs,
) -> bytes:
    """Return UTF-8 encoded bytes (with BOM for Excel compatibility)."""
    csv_str = export_enriched_csv(df, workspace, **kwargs)
    return b"\xef\xbb\xbf" + csv_str.encode("utf-8")
