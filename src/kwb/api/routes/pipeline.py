"""
Pipeline step state management.

Tracks the 7-step curation pipeline workflow:
1. Upload & Parse
2. Data Extraction (NER + Image)
3. Quality Gateway
4. Full Run
5. Enrichment
6. Dictionary
7. Metadata Enrichment & Export

Router prefix: /api/pipeline
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError("pip install fastapi")

from kwb.api.deps import get_state, get_datasets, get_workspace

router = APIRouter()

STEP_DEFS = [
    {
        "number": 1, "key": "upload",
        "name": "Upload & Parse",
        "name_de": "Daten laden & Parsen",
    },
    {
        "number": 2, "key": "extraction",
        "name": "Data Extraction",
        "name_de": "Datenextraktion",
    },
    {
        "number": 3, "key": "quality",
        "name": "Quality Gateway",
        "name_de": "Qualitätskontrolle",
    },
    {
        "number": 4, "key": "fullrun",
        "name": "Full Run",
        "name_de": "Gesamtlauf",
    },
    {
        "number": 5, "key": "enrichment",
        "name": "Enrichment",
        "name_de": "Anreicherung",
    },
    {
        "number": 6, "key": "dictionary",
        "name": "Dictionary",
        "name_de": "Wörterbuch",
    },
    {
        "number": 7, "key": "export",
        "name": "Metadata Enrichment & Export",
        "name_de": "Metadaten-Anreicherung & Export",
    },
]


def _get_pipeline_state() -> dict:
    """Get or initialize pipeline state in the global state dict."""
    state = get_state()
    if "pipeline" not in state:
        state["pipeline"] = {
            "active_step": 1,
            "completed_steps": [],
            "test_batch_ner": False,
            "test_batch_images": False,
            "test_batch_reviewed": False,
            "full_run_ner": False,
            "full_run_images": False,
        }
    return state["pipeline"]


def _compute_step_status(step_num: int, pipeline: dict) -> str:
    """Determine status of a step: completed, active, or locked."""
    if step_num in pipeline.get("completed_steps", []):
        return "completed"
    if step_num == pipeline.get("active_step", 1):
        return "active"
    return "locked"


def _check_prerequisites(step_num: int, pipeline: dict) -> tuple[bool, str]:
    """Check if prerequisites for a step are met."""
    datasets = get_datasets()
    ws = get_workspace()

    if step_num == 1:
        return True, ""

    if step_num == 2:
        if not datasets:
            return False, "Zuerst Daten hochladen (Schritt 1)"
        return True, ""

    if step_num == 3:
        if not pipeline.get("test_batch_ner") and \
           not pipeline.get("test_batch_images"):
            return False, "Zuerst 2%-Testlauf ausführen (Schritt 2)"
        return True, ""

    if step_num == 4:
        if not pipeline.get("test_batch_reviewed"):
            return False, "Testlauf-Ergebnisse prüfen (Schritt 3)"
        return True, ""

    if step_num == 5:
        if not pipeline.get("full_run_ner") and \
           not pipeline.get("full_run_images"):
            return False, "Gesamtlauf ausführen (Schritt 4)"
        return True, ""

    if step_num == 6:
        if not ws.dictionary:
            return False, "Daten anreichern (Schritt 5)"
        return True, ""

    if step_num == 7:
        has_authority = any(
            e.has_authority for e in ws.dictionary
        )
        if not has_authority and not ws.dictionary:
            return False, "Wörterbuch aufbauen (Schritt 6)"
        return True, ""

    return True, ""


@router.get("/api/pipeline/steps")
async def get_steps():
    """Return all 7 pipeline steps with their current status."""
    pipeline = _get_pipeline_state()
    datasets = get_datasets()
    ws = get_workspace()

    steps = []
    for sd in STEP_DEFS:
        n = sd["number"]
        can_activate, reason = _check_prerequisites(n, pipeline)
        status = _compute_step_status(n, pipeline)

        # If locked but prerequisites met, show as available
        if status == "locked" and can_activate:
            status = "available"

        step_info = {
            "number": n,
            "key": sd["key"],
            "name": sd["name"],
            "name_de": sd["name_de"],
            "status": status,
            "can_activate": can_activate,
            "locked_reason": reason if not can_activate else "",
        }

        # Add context counts
        if n == 1:
            step_info["datasets"] = len(datasets)
        elif n == 2:
            step_info["test_batch_ner"] = pipeline.get(
                "test_batch_ner", False
            )
            step_info["test_batch_images"] = pipeline.get(
                "test_batch_images", False
            )
        elif n == 5:
            step_info["dictionary_count"] = len(ws.dictionary)
        elif n == 6:
            authority_count = sum(
                1 for e in ws.dictionary if e.has_authority
            )
            step_info["authority_count"] = authority_count

        steps.append(step_info)

    return {
        "active_step": pipeline.get("active_step", 1),
        "steps": steps,
    }


@router.post("/api/pipeline/step/{step_num}/activate")
async def activate_step(step_num: int):
    """Move to a specific step (if prerequisites are met)."""
    if step_num < 1 or step_num > 7:
        return JSONResponse({"error": "Ungültiger Schritt"}, 400)

    pipeline = _get_pipeline_state()
    can_activate, reason = _check_prerequisites(step_num, pipeline)

    if not can_activate:
        return JSONResponse({"error": reason}, 400)

    pipeline["active_step"] = step_num
    return {"active_step": step_num, "status": "ok"}


@router.post("/api/pipeline/step/{step_num}/complete")
async def complete_step(step_num: int):
    """Mark a step as completed."""
    if step_num < 1 or step_num > 7:
        return JSONResponse({"error": "Ungültiger Schritt"}, 400)

    pipeline = _get_pipeline_state()

    if step_num not in pipeline["completed_steps"]:
        pipeline["completed_steps"].append(step_num)

    # Auto-advance to next step if not already past it
    if step_num >= pipeline.get("active_step", 1) and step_num < 7:
        pipeline["active_step"] = step_num + 1

    return {"completed": pipeline["completed_steps"], "active_step": pipeline["active_step"]}


@router.post("/api/pipeline/mark")
async def mark_pipeline_flag(request: dict):
    """Set a pipeline flag (e.g., test_batch_ner=True)."""
    pipeline = _get_pipeline_state()
    allowed = {
        "test_batch_ner", "test_batch_images", "test_batch_reviewed",
        "full_run_ner", "full_run_images",
    }
    for key, value in request.items():
        if key in allowed:
            pipeline[key] = bool(value)
    return {"pipeline": pipeline}
