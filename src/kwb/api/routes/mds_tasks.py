"""
MDS validation and Task management routes.

Router prefix: /api
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError("pip install fastapi")

from kwb.api.deps import get_workspace, get_datasets
from kwb.core.mds import (
    MdsFieldDef, MDS_11_FIELDS, validate_mds,
)
from kwb.core.tasks import generate_tasks_from_mds

router = APIRouter()


# ---------------------------------------------------------------------------
# MDS Validation
# ---------------------------------------------------------------------------

@router.post("/api/mds/validate")
async def mds_validate(request: dict):
    """
    Validate a dataset against MDS fields.

    Request body:
        dataset: str          — dataset name
        include_custom: bool  — also check custom MDS fields from workspace
    """
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds
    ws = get_workspace()

    # Build custom fields from workspace
    custom_fields = None
    if request.get("include_custom", True) and ws.custom_mds_fields:
        custom_fields = [MdsFieldDef.from_dict(f) for f in ws.custom_mds_fields]

    report = validate_mds(
        df, ws.active_mappings(),
        mds_fields=MDS_11_FIELDS,
        custom_fields=custom_fields,
    )
    return report.to_dict()


@router.get("/api/mds/fields")
async def mds_fields():
    """Return MDS 1.1 standard fields plus any custom fields."""
    ws = get_workspace()
    standard = [f.to_dict() for f in MDS_11_FIELDS]
    custom = ws.custom_mds_fields
    return {"standard": standard, "custom": custom}


@router.post("/api/mds/custom-field")
async def add_custom_mds_field(request: dict):
    """Add a custom MDS field definition."""
    ws = get_workspace()
    mds_name = (request.get("mds_name") or "").strip()
    goobi_type = (request.get("goobi_type") or "").strip()
    if not mds_name or not goobi_type:
        return JSONResponse({"error": "mds_name und goobi_type erforderlich"}, 400)

    requirement = request.get("requirement", "recommended")
    if requirement not in {"required", "recommended", "optional"}:
        return JSONResponse({"error": f"Ungültiger Wert für requirement: '{requirement}'. Erlaubt: required, recommended, optional"}, 400)
    note = request.get("note", "")

    # Check for duplicates
    for f in ws.custom_mds_fields:
        if f.get("mds_name") == mds_name:
            return JSONResponse({"error": f"Feld '{mds_name}' existiert bereits"}, 409)

    ws.custom_mds_fields.append({
        "mds_name": mds_name,
        "goobi_type": goobi_type,
        "requirement": requirement,
        "note": note,
    })
    ws._touch()
    return {"ok": True, "custom_fields": ws.custom_mds_fields}


@router.delete("/api/mds/custom-field/{idx}")
async def delete_custom_mds_field(idx: int):
    """Remove a custom MDS field by index."""
    ws = get_workspace()
    if idx < 0 or idx >= len(ws.custom_mds_fields):
        return JSONResponse({"error": "Index ungültig"}, 400)
    removed = ws.custom_mds_fields.pop(idx)
    ws._touch()
    return {"ok": True, "removed": removed}


# ---------------------------------------------------------------------------
# Task Management
# ---------------------------------------------------------------------------

@router.post("/api/tasks/generate")
async def generate_tasks(request: dict):
    """
    Generate tasks from MDS validation gaps.

    Request body:
        dataset: str — dataset name to validate and generate tasks for
    """
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds
    ws = get_workspace()

    custom_fields = None
    if ws.custom_mds_fields:
        custom_fields = [MdsFieldDef.from_dict(f) for f in ws.custom_mds_fields]

    report = validate_mds(df, ws.active_mappings(), custom_fields=custom_fields)
    new_tasks = generate_tasks_from_mds(report)

    # Merge with existing tasks (don't duplicate)
    existing_keys = {
        (t.get("mds_field", ""), t.get("category", ""))
        for t in ws.tasks
    }
    added = 0
    for task in new_tasks:
        key = (task.mds_field, task.category.value)
        if key not in existing_keys:
            ws.tasks.append(task.to_dict())
            existing_keys.add(key)
            added += 1

    ws._touch()
    return {
        "generated": len(new_tasks),
        "added": added,
        "total": len(ws.tasks),
        "tasks": ws.tasks,
    }


@router.get("/api/tasks")
async def list_tasks(status: str = ""):
    """List all tasks, optionally filtered by status."""
    ws = get_workspace()
    tasks = ws.tasks
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    return {"tasks": tasks, "total": len(tasks)}


@router.post("/api/tasks/{task_id}/update")
async def update_task(task_id: str, request: dict):
    """Update a task's status or note."""
    ws = get_workspace()
    for task in ws.tasks:
        if task.get("task_id") == task_id:
            new_status = request.get("status")
            if new_status:
                task["status"] = new_status
                if new_status in ("done", "skipped"):
                    from datetime import datetime
                    task["completed_at"] = datetime.utcnow().isoformat()
            if "note" in request:
                task["note"] = request["note"]
            ws._touch()
            return {"ok": True, "task": task}
    return JSONResponse({"error": "Task nicht gefunden"}, 404)


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task."""
    ws = get_workspace()
    for i, task in enumerate(ws.tasks):
        if task.get("task_id") == task_id:
            removed = ws.tasks.pop(i)
            ws._touch()
            return {"ok": True, "removed": removed}
    return JSONResponse({"error": "Task nicht gefunden"}, 404)


@router.post("/api/tasks/clear-done")
async def clear_done_tasks():
    """Remove all completed/skipped tasks."""
    ws = get_workspace()
    before = len(ws.tasks)
    ws.tasks = [t for t in ws.tasks if t.get("status") not in ("done", "skipped")]
    ws._touch()
    return {"removed": before - len(ws.tasks), "remaining": len(ws.tasks)}


# ---------------------------------------------------------------------------
# AI-powered MDS field mapping suggestions
# ---------------------------------------------------------------------------

@router.post("/api/mds/ai-suggest")
async def mds_ai_suggest(request: dict):
    """
    Use AI to suggest mappings from CSV columns to MDS Pflicht-/Empfohlene Felder.

    Request body:
        dataset: str
        columns: list[{name, fill_rate, sample_values}]
        mds_fields: list[{mds, goobi, pflicht, note}]
    """
    from kwb.api.deps import get_provider

    columns = request.get("columns", [])
    mds_fields = request.get("mds_fields", [])

    if not columns:
        return JSONResponse({"error": "Keine Spalten"}, 400)

    # Build a prompt for the AI
    col_desc = "\n".join(
        f"- {c['name']} (Füllgrad: {round(c.get('fill_rate', 0) * 100)}%, "
        f"Beispiele: {', '.join(str(v) for v in (c.get('sample_values') or [])[:3])})"
        for c in columns
    )
    mds_desc = "\n".join(
        f"- {f['mds']} → Goobi-Typ: {f['goobi']} "
        f"({'PFLICHT' if f.get('pflicht') else 'Empfohlen'}): {f.get('note', '')}"
        for f in mds_fields
    )

    prompt = (
        "Du bist ein Experte für Museumsdaten und den Minimaldatensatz (minimaldatensatz.de).\n\n"
        "Hier sind die CSV-Spalten eines GLAM-Datensatzes:\n"
        f"{col_desc}\n\n"
        "Hier sind die Felder des Minimaldatensatz 1.1:\n"
        f"{mds_desc}\n\n"
        "Ordne jede CSV-Spalte dem passendsten MDS-Feld zu. "
        "Priorisiere Pflichtfelder. Wenn keine gute Zuordnung möglich ist, überspringe die Spalte.\n\n"
        'Antworte als JSON-Array: [{"csv_column":"...","mds_field":"...","goobi_type":"...","reason":"..."}]\n'
        "Nur das JSON-Array, kein anderer Text."
    )

    try:
        provider = get_provider()
        from kwb.ai.provider import AIMessage
        messages = [
            AIMessage.system(
                "Du bist ein Experte für GLAM-Metadaten und den deutschen Minimaldatensatz. "
                "Antworte immer als valides JSON."
            ),
            AIMessage.user(prompt),
        ]
        response = provider.complete(messages, temperature=0.1, max_tokens=2048)
        content = response.content.strip()

        # Parse JSON from response (handle markdown code blocks)
        import json as _json
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        suggestions = _json.loads(content)

        # Validate suggestions
        valid = []
        col_names = {c["name"] for c in columns}
        goobi_types = {f["goobi"] for f in mds_fields}
        for s in suggestions:
            if (
                isinstance(s, dict)
                and s.get("csv_column") in col_names
                and s.get("goobi_type") in goobi_types
            ):
                valid.append(s)

        return {"suggestions": valid, "model": response.model}
    except Exception as e:
        logger.exception("AI MDS suggestion failed")
        # Fallback: heuristic-based suggestions
        return _heuristic_mds_suggestions(columns, mds_fields)


def _heuristic_mds_suggestions(
    columns: list[dict], mds_fields: list[dict]
) -> dict:
    """Fallback heuristic when AI is not available."""
    suggestions = []
    col_names_lower = {c["name"]: c["name"] for c in columns}
    for c in columns:
        col_names_lower[c["name"].lower()] = c["name"]

    for f in mds_fields:
        candidates = [
            f["mds"].lower(),
            f["goobi"].lower(),
            *f["mds"].lower().split("/"),
        ]
        for cand in candidates:
            for col_lower, col_orig in col_names_lower.items():
                if cand in col_lower or col_lower in cand:
                    suggestions.append({
                        "csv_column": col_orig,
                        "mds_field": f["mds"],
                        "goobi_type": f["goobi"],
                        "reason": "Namensähnlichkeit (heuristisch)",
                    })
                    break
            else:
                continue
            break

    return {"suggestions": suggestions, "model": "heuristic"}
