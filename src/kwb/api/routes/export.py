"""
Export routes: Goobi XML preview, batch export, CSV enriched, JSON-LD.

Router prefix: /api
"""
from __future__ import annotations

import csv
import io
import json
import logging

logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse, Response
except ImportError:
    raise ImportError("pip install fastapi")

from kwb.api.deps import get_datasets, get_workspace
from kwb.export.goobi_xml import export_goobi_xml, export_goobi_batch

router = APIRouter()


def _build_image_result_rows(ws):
    rows = []
    for r in ws.image_analyses:
        payload = r.result if isinstance(r.result, dict) else {}
        rows.append({
            "image_id": r.image_id,
            "record_id": r.record_id,
            "filename": r.filename,
            "review_status": r.review_status.value,
            "review_comment": r.review_comment,
            "reviewer": r.reviewer,
            "confidence": r.confidence,
            "description": payload.get("description", ""),
            "objects": "; ".join(payload.get("objects", []) or []),
            "persons": "; ".join(payload.get("persons", []) or []),
            "places": "; ".join(payload.get("places", []) or []),
            "style": payload.get("style", ""),
            "period": payload.get("period", ""),
            "provenance": json.dumps(r.provenance, ensure_ascii=False),
        })
    return rows




def _validate_review_status(review_status: str, rows: list[dict]) -> list[dict]:
    if not review_status:
        return rows
    allowed = {"pending", "accepted", "rejected"}
    if review_status not in allowed:
        return []
    return [r for r in rows if r["review_status"] == review_status]

def _image_rows_as_jsonld(rows, base_url: str = "https://example.org/images/") -> dict:
    context = {
        "@vocab": "https://schema.org/",
        "prov": "http://www.w3.org/ns/prov#",
        "reviewStatus": "prov:wasInvalidatedBy",
        "confidence": "http://example.org/vocab/confidence",
    }
    graph = []
    for row in rows:
        graph.append({
            "@id": f"{base_url}{row['image_id']}",
            "@type": "ImageObject",
            "identifier": row["image_id"],
            "name": row["filename"],
            "isPartOf": row.get("record_id") or None,
            "description": row.get("description", ""),
            "keywords": [x for x in row.get("objects", "").split("; ") if x],
            "contentLocation": [x for x in row.get("places", "").split("; ") if x],
            "about": [x for x in row.get("persons", "").split("; ") if x],
            "confidence": row.get("confidence", 0),
            "reviewStatus": row.get("review_status", "pending"),
            "comment": row.get("review_comment", ""),
            "creator": row.get("reviewer", ""),
            "prov:wasGeneratedBy": row.get("provenance", ""),
        })
    return {"@context": context, "@graph": graph}


@router.post("/api/export/goobi-preview")
async def export_preview(request: dict):
    """
    Generate Goobi XML for a single record (preview / dry-run).
    """
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds
    ws = get_workspace()
    rid = request.get("record_id", "")

    if rid:
        id_col = profile.id_column or df.columns[0]
        subset = df[df[id_col].astype(str) == rid]
        if subset.empty:
            return JSONResponse({"error": f"Record '{rid}' nicht gefunden"}, 400)
    else:
        subset = df.head(1)
        if subset.empty:
            return JSONResponse({"error": "Keine Daten"}, 400)
        id_col = profile.id_column or df.columns[0]
        rid = str(subset.iloc[0][id_col])

    try:
        results = export_goobi_xml(subset, ws)
        if results:
            _, xml_str = results[0]
            return {"xml": xml_str, "record_id": rid}
        return JSONResponse({"error": "Export fehlgeschlagen"}, 500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@router.post("/api/export/goobi-batch")
async def export_batch(request: dict):
    """
    Export all records as a Goobi XML batch (zipped or concatenated).
    """
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds
    ws = get_workspace()
    limit = min(request.get("limit", 500), 5000)
    try:
        xml = export_goobi_batch(df.head(limit), ws)
        return {
            "xml": xml,
            "record_count": min(len(df), limit),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@router.post("/api/export/csv")
async def export_csv(request: dict):
    """
    Export enriched CSV (F34): original columns + NER/EDTF/GND enrichments.

    Request body:
        dataset: str          — dataset name (required)
        include_ner: bool     — add ner_* columns (default true)
        include_edtf: bool    — add edtf_* columns (default true)
        include_gnd: bool     — add gnd_ids column (default true)
        limit: int            — max rows (default 10000)
    """
    dsn = request.get("dataset", "")
    if not dsn:
        datasets = get_datasets()
        if datasets:
            dsn = next(iter(datasets))
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)

    df, profile = ds
    ws = get_workspace()
    limit = min(request.get("limit", 10_000), 100_000)

    try:
        from kwb.export.csv_export import export_enriched_csv_bytes
        csv_bytes = export_enriched_csv_bytes(
            df.head(limit), ws,
            include_ner=request.get("include_ner", True),
            include_edtf=request.get("include_edtf", True),
            include_gnd=request.get("include_gnd", True),
            id_column=profile.id_column or df.columns[0],
        )
        filename = f"{dsn}_enriched.csv"
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.exception("CSV export failed")
        return JSONResponse({"error": str(e)}, 500)


@router.post("/api/export/jsonld")
async def export_jsonld_route(request: dict):
    """
    Export JSON-LD (F35): Linked Open Data for GLAM records.

    Request body:
        dataset: str        — dataset name (required)
        base_url: str       — base URI for record identifiers
        limit: int          — max records (default 1000)
        as_file: bool       — return as downloadable file (default false)
    """
    dsn = request.get("dataset", "")
    if not dsn:
        datasets = get_datasets()
        if datasets:
            dsn = next(iter(datasets))
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)

    df, _profile = ds
    ws = get_workspace()
    limit = min(request.get("limit", 1000), 50_000)
    base_url = request.get("base_url", "https://example.org/collection/")

    try:
        from kwb.export.jsonld import export_jsonld
        jsonld_str = export_jsonld(df, ws, base_url=base_url, limit=limit)

        if request.get("as_file", False):
            return Response(
                content=jsonld_str.encode("utf-8"),
                media_type="application/ld+json",
                headers={"Content-Disposition": f'attachment; filename="{dsn}.jsonld"'},
            )

        import json
        return {"jsonld": json.loads(jsonld_str), "record_count": min(len(df), limit)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)



@router.post("/api/export/image-results")
async def export_image_results(request: dict):
    """Export image analysis results including review status and provenance."""
    ws = get_workspace()
    rows = _build_image_result_rows(ws)
    review_status = request.get("review_status", "")
    rows = _validate_review_status(review_status, rows)
    if review_status and not rows:
        return JSONResponse({"error": "Ungültiger oder leerer review_status-Filter"}, 400)

    fmt = (request.get("format", "csv") or "csv").lower()
    if fmt == "csv":
        fieldnames = [
            "image_id", "record_id", "filename", "review_status", "review_comment",
            "reviewer", "confidence", "description", "objects", "persons", "places",
            "style", "period", "provenance",
        ]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
        return Response(
            content=("\ufeff" + buf.getvalue()).encode("utf-8"),
            media_type="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": 'attachment; filename="image_results.csv"'},
        )

    if fmt == "jsonld":
        base_url = request.get("base_url", "https://example.org/images/")
        doc = _image_rows_as_jsonld(rows, base_url=base_url)
        payload = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
        if request.get("as_file", True):
            return Response(
                content=payload,
                media_type="application/ld+json",
                headers={"Content-Disposition": 'attachment; filename="image_results.jsonld"'},
            )
        return {"jsonld": doc, "count": len(rows)}

    return JSONResponse({"error": "format must be csv or jsonld"}, 400)
