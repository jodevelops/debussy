"""
Export routes: Goobi XML preview, batch export, CSV enriched, JSON-LD.

Router prefix: /api
"""
from __future__ import annotations

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


def _ensure_ai_review_completed(ws):
    if ws.has_pending_ai_suggestions():
        return JSONResponse({
            "error": "Es gibt noch ungeprüfte KI-Vorschläge. Bitte im Bild-Tab freigeben/ablehnen.",
            "review": ws.image_review_stats(),
        }, 409)
    return None



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
    review_block = _ensure_ai_review_completed(ws)
    if review_block:
        return review_block
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
    review_block = _ensure_ai_review_completed(ws)
    if review_block:
        return review_block
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
    review_block = _ensure_ai_review_completed(ws)
    if review_block:
        return review_block
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
    review_block = _ensure_ai_review_completed(ws)
    if review_block:
        return review_block
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

