"""
Export routes: Goobi XML preview, batch export.

Router prefix: /api
"""
from __future__ import annotations

try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError("pip install fastapi")

from kwb.api.deps import get_datasets, get_workspace
from kwb.export.goobi_xml import export_goobi_xml, export_goobi_batch

router = APIRouter()


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
