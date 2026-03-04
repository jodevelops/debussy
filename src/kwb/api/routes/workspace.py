"""
Workspace routes: field mapping, entity review, dictionary, save/load.

Router prefix: /api/workspace
"""
from __future__ import annotations

import json
from pathlib import Path

try:
    from fastapi import APIRouter, File, UploadFile
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError("pip install fastapi")

from kwb.api.deps import (
    ALLOWED_WS_EXT, MAX_WORKSPACE_BYTES,
    get_workspace, set_workspace,
    workspace_dir, safe_filename,
)
from kwb.core.workspace import FieldMapping, Workspace

router = APIRouter()


@router.post("/api/workspace/field-mapping")
async def set_field_mapping(request: dict):
    ws = get_workspace()
    mappings_raw = request.get("mappings", [])
    mappings = [
        FieldMapping(
            csv_column=m["csv_column"],
            goobi_type=m.get("goobi_type", ""),
            repeatable=m.get("repeatable", False),
            authority=m.get("authority", ""),
            authority_uri=m.get("authority_uri", ""),
            enabled=m.get("enabled", True),
        )
        for m in mappings_raw
        if m.get("csv_column")
    ]
    ws.set_field_mapping(mappings)
    return {"saved": len(mappings), "mappings": [m.to_dict() for m in ws.active_mappings()]}


@router.get("/api/workspace/field-mapping")
async def get_field_mapping():
    ws = get_workspace()
    return {"mappings": [m.to_dict() for m in ws.active_mappings()]}


@router.get("/api/workspace")
async def workspace_summary():
    return get_workspace().to_summary()


@router.get("/api/workspace/entities")
async def workspace_entities(status: str = ""):
    ws = get_workspace()
    from kwb.core.workspace import ReviewStatus
    if status:
        try:
            s = ReviewStatus(status)
            return {"entities": [e.to_dict() for e in ws.reviews_by_status(s)]}
        except ValueError:
            return JSONResponse({"error": f"Unknown status '{status}'"}, 400)
    return {"entities": [e.to_dict() for e in ws.entity_reviews]}


@router.post("/api/workspace/entity/batch")
async def batch_update_entities(request: dict):
    ws = get_workspace()

    # Support new format: {"indices": [...], "updates": {...}}
    indices = request.get("indices", [])
    updates = request.get("updates", {})

    if indices and updates:
        changed = 0
        for idx in indices:
            if ws.update_entity(idx, updates):
                changed += 1
        return {"updated": changed, "stats": ws.review_stats()}

    # Legacy format: {"updates": [{"idx": ..., "action": ...}]}
    update_list = request.get("updates", [])
    if isinstance(update_list, list):
        changed = 0
        for upd in update_list:
            idx = upd.get("idx")
            action = upd.get("action", "")
            if idx is None or idx < 0 or idx >= len(ws.entity_reviews):
                continue
            er = ws.entity_reviews[idx]
            if action == "accept":
                er.accept(gnd_id=upd.get("gnd_id"), gnd_preferred=upd.get("gnd_preferred"))
            elif action == "reject":
                er.reject(note=upd.get("note", ""))
            changed += 1
        return {"updated": changed, "stats": ws.review_stats()}

    return JSONResponse({"error": "Invalid request format"}, 400)


@router.post("/api/workspace/entity/{idx}")
async def update_entity(idx: int, request: dict):
    ws = get_workspace()
    if idx < 0 or idx >= len(ws.entity_reviews):
        return JSONResponse({"error": "Index out of range"}, 404)

    # Support both action-based and direct update patterns
    action = request.get("action", "")
    er = ws.entity_reviews[idx]

    if action == "accept":
        er.accept(
            gnd_id=request.get("gnd_id", ""),
            gnd_preferred=request.get("gnd_preferred", ""),
            note=request.get("note", ""),
        )
    elif action == "reject":
        er.reject(note=request.get("note", ""))
    else:
        # Direct field update (used by newer tests)
        ws.update_entity(idx, request)

    return {"ok": True, "entity": er.to_dict(), "stats": ws.review_stats()}


@router.get("/api/workspace/dictionary")
async def workspace_dictionary():
    ws = get_workspace()
    return {"entries": [e.to_dict() for e in ws.dictionary]}


@router.post("/api/workspace/save")
async def workspace_save(request: dict):
    ws = get_workspace()
    name = request.get("name", ws.name) or "project"
    fname = safe_filename(name)
    path = workspace_dir() / fname
    try:
        path.relative_to(workspace_dir())
    except ValueError:
        return JSONResponse({"error": "Invalid path"}, 400)
    ws.name = name
    ws.save(str(path))
    return {"saved": fname, "path": str(path), "size": path.stat().st_size}


@router.post("/api/workspace/load")
async def workspace_load(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_WS_EXT:
        return JSONResponse({"error": "Nur .json erlaubt"}, 400)
    content = await file.read()
    if len(content) > MAX_WORKSPACE_BYTES:
        return JSONResponse({"error": "Datei zu groß"}, 400)
    try:
        data = json.loads(content.decode("utf-8"))
        ws = Workspace.from_dict(data)
    except Exception as e:
        return JSONResponse({"error": f"Ungültige Datei: {e}"}, 400)
    set_workspace(ws)
    return ws.to_summary()
