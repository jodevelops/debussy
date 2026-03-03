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
    if not rid and len(df) > 0:
        id_col = profile.id_column or df.columns[0]
        rid = str(df.iloc[0][id_col])
    mapping = {m.csv_column: m.goobi_type for m in ws.active_mappings()}
    try:
        xml_str = export_goobi_xml(df, profile, rid, mapping=mapping)
        return {"xml": xml_str, "record_id": rid}
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
    mapping = {m.csv_column: m.goobi_type for m in ws.active_mappings()}
    limit = min(request.get("limit", 500), 5000)
    try:
        results = export_goobi_batch(df.head(limit), profile, mapping=mapping)
        return {
            "total": len(results),
            "succeeded": len([r for r in results if r.get("xml")]),
            "records": results[:100],
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)
