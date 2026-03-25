"""
Phase 3 — Review Queues, Work Packages & Remediation — API Routes.

Endpoints:

  GET  /api/review/items                — list review items (filterable)
  PATCH /api/review/items/{item_id}/status — update item status
  GET  /api/review/items/summary        — queue summary statistics
  GET  /api/review/work-packages        — list work packages
  POST /api/review/work-packages/generate — generate from last quality analysis
  GET  /api/review/suggestions          — list remediation suggestions
  POST /api/review/suggestions          — add a remediation suggestion
  PATCH /api/review/suggestions/{sid}/status — accept/reject a suggestion
  POST /api/review/apply                — apply all ACCEPTED suggestions to dataset
  GET  /api/review/changelog            — applied change log
  GET  /api/review/export               — export review status + changelog as JSON
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError("pip install fastapi uvicorn")

from kwb.api.deps import get_datasets, get_state
from kwb.core.models import (
    AppliedChangeLog,
    RemediationActionType,
    RemediationSuggestion,
    ReviewStatus,
    WorkPackage,
)
from kwb.review.queue import ReviewQueue
from kwb.review.remediation import apply_accepted_changes
from kwb.review.work_packages import generate_work_packages

router = APIRouter(prefix="/api/review", tags=["review"])

_VALID_STATUSES = {s.value for s in ReviewStatus}
_VALID_ACTIONS = {a.value for a in RemediationActionType}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helper: get or init review queue from state
# ---------------------------------------------------------------------------

def _get_queue(state: dict) -> ReviewQueue:
    if state["review_queue"] is None:
        state["review_queue"] = ReviewQueue()
    return state["review_queue"]


# ---------------------------------------------------------------------------
# Review Items
# ---------------------------------------------------------------------------

@router.get("/items/summary")
async def review_items_summary():
    """Gibt Zusammenfassung der Review-Queue zurück (Anzahl nach Status, Severity, Kategorie)."""
    state = get_state()
    queue = _get_queue(state)
    return {"status": "ok", "summary": queue.summary()}


@router.get("/items")
async def list_review_items(
    severity: str | None = None,
    column: str | None = None,
    category: str | None = None,
    status: str | None = None,
    min_confidence: float | None = None,
    max_confidence: float | None = None,
    source: str | None = None,
    is_ai_based: bool | None = None,
    limit: int = 200,
    offset: int = 0,
):
    """
    Listet Review-Items gefiltert nach Severity, Spalte, Kategorie, Status oder Confidence.

    Filter-Parameter (alle optional):
      severity         — critical|warning|info
      column           — Spaltenname
      category         — FindingCategory-Wert (z. B. field_misuse)
      status           — pending|accepted|rejected|needs_expert_review|applied
      min_confidence   — Untergrenze Confidence (0.0–1.0)
      max_confidence   — Obergrenze Confidence (0.0–1.0)
      source           — Datensatzname
      is_ai_based      — true|false
      limit            — Maximalanzahl Ergebnisse (Standard: 200)
      offset           — Seitenversatz
    """
    state = get_state()
    queue = _get_queue(state)

    items = queue.filter(
        severity=severity,
        column=column,
        category=category,
        status=status,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        source=source,
        is_ai_based=is_ai_based,
    )
    total = len(items)
    page = items[offset: offset + limit]
    return {
        "status": "ok",
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [i.to_dict() for i in page],
    }


@router.patch("/items/{item_id}/status")
async def update_item_status(item_id: str, request: dict | None = None):
    """
    Aktualisiert den Bearbeitungsstatus eines Review-Items.

    Request body:
      status    — pending|accepted|rejected|needs_expert_review|applied (Pflicht)
      reviewer  — Name/ID des Bearbeiters (optional)
      note      — Notiz zur Entscheidung (optional)
    """
    request = request or {}
    new_status_raw = request.get("status", "")
    if new_status_raw not in _VALID_STATUSES:
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "message": f"Ungültiger Status '{new_status_raw}'. Erlaubt: {sorted(_VALID_STATUSES)}",
            },
        )

    state = get_state()
    queue = _get_queue(state)
    item = queue.update_status(
        item_id=item_id,
        new_status=ReviewStatus(new_status_raw),
        reviewer=request.get("reviewer"),
        note=request.get("note"),
    )
    if item is None:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": f"Item '{item_id}' nicht gefunden."},
        )
    return {"status": "ok", "item": item.to_dict()}


# ---------------------------------------------------------------------------
# Work Packages
# ---------------------------------------------------------------------------

@router.get("/work-packages")
async def list_work_packages(status: str | None = None):
    """Gibt alle Work Packages zurück, optional gefiltert nach Status."""
    state = get_state()
    packages: list[WorkPackage] = state.get("work_packages", [])
    if status is not None:
        packages = [p for p in packages if p.status.value == status]
    return {
        "status": "ok",
        "total": len(packages),
        "work_packages": [p.to_dict() for p in packages],
    }


@router.post("/work-packages/generate")
async def generate_packages(request: dict | None = None):
    """
    Generiert Work Packages aus dem letzten Qualitätsbericht.

    Benötigt, dass zuvor eine Qualitätsanalyse durchgeführt wurde
    (POST /api/analyze oder POST /api/ai/quality-check).

    Request body (optional):
      dataset_id  — Datensatz-ID (optional, verwendet letzten Bericht)
    """
    state = get_state()
    report = state.get("report")
    if report is None:
        return JSONResponse(
            status_code=404,
            content={
                "status": "error",
                "message": "Kein Qualitätsbericht vorhanden. Bitte zuerst Analyse durchführen.",
            },
        )

    # report can be AnalysisReport or QualityAnalysisReport
    from kwb.core.models import QualityAnalysisReport, AnalysisReport
    from kwb.analyze.quality_report import build_quality_analysis_report

    if isinstance(report, AnalysisReport):
        quality_report = build_quality_analysis_report(report)
    elif isinstance(report, QualityAnalysisReport):
        quality_report = report
    else:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Ungültiger Berichtstyp im Zustand."},
        )

    queue = _get_queue(state)
    packages = generate_work_packages(quality_report, queue=queue)
    state["work_packages"] = packages

    return {
        "status": "ok",
        "total": len(packages),
        "work_packages": [p.to_dict() for p in packages],
    }


@router.post("/queue/build")
async def build_review_queue(request: dict | None = None):
    """
    Baut die Review-Queue aus dem letzten Qualitätsbericht auf.

    Löscht ggf. bestehende Queue und erstellt sie neu.

    Request body (optional):
      is_ai_based  — bool, ob die Befunde KI-basiert sind (Standard: false)
      source       — Datensatzname (optional)
    """
    request = request or {}
    state = get_state()
    report = state.get("report")
    if report is None:
        return JSONResponse(
            status_code=404,
            content={
                "status": "error",
                "message": "Kein Qualitätsbericht vorhanden. Bitte zuerst Analyse durchführen.",
            },
        )

    from kwb.core.models import QualityAnalysisReport, AnalysisReport
    from kwb.analyze.quality_report import build_quality_analysis_report

    if isinstance(report, AnalysisReport):
        quality_report = build_quality_analysis_report(report)
    elif isinstance(report, QualityAnalysisReport):
        quality_report = report
    else:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Ungültiger Berichtstyp im Zustand."},
        )

    is_ai_based: bool = bool(request.get("is_ai_based", False))
    source: str = request.get("source", "")

    queue = ReviewQueue.from_quality_report(quality_report, source=source, is_ai_based=is_ai_based)
    state["review_queue"] = queue

    return {
        "status": "ok",
        "summary": queue.summary(),
    }


# ---------------------------------------------------------------------------
# Remediation Suggestions
# ---------------------------------------------------------------------------

@router.get("/suggestions")
async def list_suggestions(item_id: str | None = None, package_id: str | None = None):
    """Listet alle Bereinigungsvorschläge, optional gefiltert nach Item oder Package."""
    state = get_state()
    sugs: dict[str, RemediationSuggestion] = state.get("suggestions", {})
    result = list(sugs.values())
    if item_id is not None:
        result = [s for s in result if s.item_id == item_id]
    if package_id is not None:
        result = [s for s in result if s.package_id == package_id]
    return {
        "status": "ok",
        "total": len(result),
        "suggestions": [s.to_dict() for s in result],
    }


@router.post("/suggestions")
async def add_suggestion(request: dict | None = None):
    """
    Fügt einen neuen Bereinigungsvorschlag hinzu.

    Request body:
      action_type      — RemediationActionType-Wert (Pflicht)
      original_value   — Originalwert (optional)
      suggested_value  — Vorgeschlagener Wert (optional)
      reasoning        — Begründung (Pflicht)
      item_id          — Verknüpftes ReviewItem (optional)
      package_id       — Verknüpftes WorkPackage (optional)
      target_field     — Zielspalte (optional)
      confidence       — Confidence 0.0–1.0 (optional)
      is_ai_based      — bool (Standard: false)
    """
    request = request or {}
    action_raw = request.get("action_type", "")
    if action_raw not in _VALID_ACTIONS:
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "message": f"Ungültiger action_type '{action_raw}'. Erlaubt: {sorted(_VALID_ACTIONS)}",
            },
        )
    reasoning = request.get("reasoning", "")
    if not reasoning:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Feld 'reasoning' ist erforderlich."},
        )

    sug = RemediationSuggestion(
        suggestion_id=_make_id(),
        action_type=RemediationActionType(action_raw),
        original_value=request.get("original_value"),
        suggested_value=request.get("suggested_value"),
        reasoning=reasoning,
        item_id=request.get("item_id"),
        package_id=request.get("package_id"),
        target_field=request.get("target_field"),
        confidence=request.get("confidence"),
        is_ai_based=bool(request.get("is_ai_based", False)),
    )
    state = get_state()
    state.setdefault("suggestions", {})[sug.suggestion_id] = sug
    return {"status": "ok", "suggestion": sug.to_dict()}


@router.patch("/suggestions/{suggestion_id}/status")
async def update_suggestion_status(suggestion_id: str, request: dict | None = None):
    """
    Akzeptiert oder verwirft einen Bereinigungsvorschlag.

    Request body:
      status    — pending|accepted|rejected (Pflicht)
      reviewer  — Name/ID des Bearbeiters (optional)
    """
    request = request or {}
    new_status_raw = request.get("status", "")
    allowed = {"pending", "accepted", "rejected"}
    if new_status_raw not in allowed:
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "message": f"Ungültiger Status '{new_status_raw}'. Erlaubt: {sorted(allowed)}",
            },
        )

    state = get_state()
    sugs: dict = state.get("suggestions", {})
    sug = sugs.get(suggestion_id)
    if sug is None:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": f"Vorschlag '{suggestion_id}' nicht gefunden."},
        )
    sug.status = ReviewStatus(new_status_raw)
    return {"status": "ok", "suggestion": sug.to_dict()}


# ---------------------------------------------------------------------------
# Apply accepted changes
# ---------------------------------------------------------------------------

@router.post("/apply")
async def apply_changes(request: dict | None = None):
    """
    Wendet alle ACCEPTED Bereinigungsvorschläge auf einen Datensatz an.

    Request body:
      dataset_id  — ID des zu bereinigenden Datensatzes (Pflicht)
      reviewer    — Name/ID des Bearbeiters (optional)
      dry_run     — bool, wenn true: nur Vorschau, keine Änderung (Standard: false)
    """
    request = request or {}
    dataset_id: str = request.get("dataset_id", "")
    if not dataset_id:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Feld 'dataset_id' ist erforderlich."},
        )

    datasets = get_datasets()
    if dataset_id not in datasets:
        return JSONResponse(
            status_code=404,
            content={
                "status": "error",
                "message": f"Datensatz '{dataset_id}' nicht gefunden.",
                "available_datasets": list(datasets.keys()),
            },
        )

    state = get_state()
    sugs: list[RemediationSuggestion] = list(state.get("suggestions", {}).values())
    reviewer: str | None = request.get("reviewer")
    dry_run: bool = bool(request.get("dry_run", False))

    accepted = [s for s in sugs if s.status == ReviewStatus.ACCEPTED]
    if not accepted:
        return {
            "status": "ok",
            "message": "Keine akzeptierten Vorschläge zum Anwenden vorhanden.",
            "applied_count": 0,
            "changelog": [],
        }

    df, profile = datasets[dataset_id]
    if dry_run:
        return {
            "status": "ok",
            "dry_run": True,
            "would_apply": len(accepted),
            "suggestions": [s.to_dict() for s in accepted],
        }

    updated_df, changelog = apply_accepted_changes(
        df=df,
        suggestions=accepted,
        dataset_id=dataset_id,
        reviewer=reviewer,
    )

    # Update dataset in state
    datasets[dataset_id] = (updated_df, profile)

    # Append changelog
    existing_log: list[AppliedChangeLog] = state.get("changelog", [])
    existing_log.extend(changelog)
    state["changelog"] = existing_log

    # Mark applied suggestions
    for sug in accepted:
        sug.status = ReviewStatus.APPLIED

    return {
        "status": "ok",
        "applied_count": len(changelog),
        "changelog": [c.to_dict() for c in changelog],
    }


# ---------------------------------------------------------------------------
# Change Log
# ---------------------------------------------------------------------------

@router.get("/changelog")
async def get_changelog(dataset_id: str | None = None, column: str | None = None):
    """Gibt das Änderungsprotokoll zurück, optional gefiltert nach Datensatz oder Spalte."""
    state = get_state()
    log: list[AppliedChangeLog] = state.get("changelog", [])
    if dataset_id is not None:
        log = [e for e in log if e.dataset_id == dataset_id]
    if column is not None:
        log = [e for e in log if e.column == column]
    return {
        "status": "ok",
        "total": len(log),
        "changelog": [e.to_dict() for e in log],
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get("/export")
async def export_review_status():
    """
    Exportiert Review-Status, Work Packages und Änderungsprotokoll als JSON.

    Eignet sich zum Archivieren oder Weitergeben des aktuellen Bearbeitungsstands.
    """
    state = get_state()
    queue = _get_queue(state)
    packages: list[WorkPackage] = state.get("work_packages", [])
    log: list[AppliedChangeLog] = state.get("changelog", [])
    sugs: dict = state.get("suggestions", {})

    return {
        "exported_at": _now_iso(),
        "review_queue": queue.to_dict(),
        "work_packages": [p.to_dict() for p in packages],
        "suggestions": [s.to_dict() for s in sugs.values()],
        "changelog": [e.to_dict() for e in log],
    }


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@router.get("/schema")
async def review_schema():
    """Gibt das Schema aller Review-Endpunkte und erlaubte Werte zurück."""
    return {
        "review_statuses": sorted(_VALID_STATUSES),
        "remediation_action_types": sorted(_VALID_ACTIONS),
        "endpoints": {
            "GET /api/review/items": "Listet Review-Items (filterable)",
            "GET /api/review/items/summary": "Queue-Zusammenfassung",
            "PATCH /api/review/items/{item_id}/status": "Status eines Items aktualisieren",
            "GET /api/review/work-packages": "Listet Work Packages",
            "POST /api/review/work-packages/generate": "Generiert Work Packages aus Qualitätsbericht",
            "POST /api/review/queue/build": "Baut Review-Queue aus Qualitätsbericht auf",
            "GET /api/review/suggestions": "Listet Bereinigungsvorschläge",
            "POST /api/review/suggestions": "Neuen Vorschlag hinzufügen",
            "PATCH /api/review/suggestions/{sid}/status": "Vorschlag akzeptieren/verwerfen",
            "POST /api/review/apply": "Akzeptierte Vorschläge auf Datensatz anwenden",
            "GET /api/review/changelog": "Änderungsprotokoll abrufen",
            "GET /api/review/export": "Kompletten Review-Status exportieren",
        },
    }
