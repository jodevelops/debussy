"""
LLM-gestützte Qualitätsprüfung — API-Route.

POST /api/ai/quality-check

Führt eine LLM-basierte semantische Qualitätsprüfung auf Zell-, Feld-,
Record- und/oder Dataset-Ebene durch. Nutzt GPUStack (oder Mock im Dev-Modus).

Request body (JSON):
  dataset_id      : str  — ID des geladenen Datensatzes
  model           : str | null  — LLM-Modell; null = Provider-Standard
  columns         : list[str] | null  — Spalten; null = alle nicht-leeren
  levels          : list[str]  — cell|column|record|dataset (default: cell,column)
  mode            : str  — pilot|full (default: pilot)
  sample_size     : int  — Zeilenanzahl im Pilotmodus (default: 50)
  field_semantics : dict  — Spalte -> Semantikbeschreibung (optional)

Response:
  status           : ok|error
  report           : LlmQualityReport als dict
  quality_analysis : QualityAnalysisReport als dict (Phase-1-Format)
  dataset_id       : str
  mode             : str
  levels           : list[str]
"""
from __future__ import annotations

try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError("pip install fastapi uvicorn")

from kwb.api.deps import get_datasets, get_provider
from kwb.analyze.llm_quality import (
    LlmAnalysisLevel,
    LlmQualityCheckMode,
    run_llm_quality_check,
)
from kwb.core.models import DatasetProfile, ColumnProfile

router = APIRouter()

_VALID_LEVELS = {lv.value for lv in LlmAnalysisLevel}
_VALID_MODES = {m.value for m in LlmQualityCheckMode}


@router.post("/api/ai/quality-check")
async def llm_quality_check(request: dict | None = None):
    """
    Startet eine LLM-gestützte Qualitätsprüfung für einen geladenen Datensatz.

    Unterstützt Pilotmodus (Stichprobe) und Vollanalyse sowie wählbare
    Analyseebenen (cell, column, record, dataset).
    """
    request = request or {}

    # --- Validate dataset ---
    dataset_id = request.get("dataset_id", "")
    datasets = get_datasets()
    if not dataset_id or dataset_id not in datasets:
        available = list(datasets.keys())
        return JSONResponse(
            status_code=404,
            content={
                "status": "error",
                "message": f"Datensatz '{dataset_id}' nicht gefunden.",
                "available_datasets": available,
            },
        )

    df = datasets[dataset_id]["df"]

    # Reconstruct a minimal DatasetProfile from stored metadata
    meta = datasets[dataset_id].get("meta", {})
    profile = _build_profile(dataset_id, df, meta)

    # --- Parse options ---
    model: str | None = request.get("model") or None
    columns: list[str] | None = request.get("columns") or None
    raw_levels: list[str] = request.get("levels") or ["cell", "column"]
    raw_mode: str = request.get("mode") or "pilot"
    sample_size: int = int(request.get("sample_size") or 50)
    field_semantics: dict[str, str] | None = request.get("field_semantics") or None

    # Validate levels
    invalid_levels = [lv for lv in raw_levels if lv not in _VALID_LEVELS]
    if invalid_levels:
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "message": f"Ungültige Analyseebenen: {invalid_levels}. "
                f"Erlaubt: {sorted(_VALID_LEVELS)}",
            },
        )

    if raw_mode not in _VALID_MODES:
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "message": f"Ungültiger Modus: '{raw_mode}'. Erlaubt: {sorted(_VALID_MODES)}",
            },
        )

    levels = [LlmAnalysisLevel(lv) for lv in raw_levels]
    mode = LlmQualityCheckMode(raw_mode)

    # Validate requested columns exist
    if columns:
        missing = [c for c in columns if c not in df.columns]
        if missing:
            return JSONResponse(
                status_code=422,
                content={
                    "status": "error",
                    "message": f"Spalten nicht im Datensatz: {missing}",
                    "available_columns": list(df.columns),
                },
            )

    # --- Run analysis ---
    provider = get_provider(model=model or "")
    try:
        llm_report = run_llm_quality_check(
            df=df,
            profile=profile,
            provider=provider,
            columns=columns,
            levels=levels,
            mode=mode,
            model=model,
            sample_size=sample_size,
            field_semantics=field_semantics,
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(exc)},
        )

    quality_analysis = llm_report.to_quality_analysis_report()

    return {
        "status": "ok",
        "dataset_id": dataset_id,
        "mode": llm_report.mode.value,
        "levels": [lv.value for lv in llm_report.levels],
        "model_used": llm_report.model_used,
        "analyzed_columns": llm_report.analyzed_columns,
        "sample_size": llm_report.sample_size,
        "analyzed_at": llm_report.analyzed_at,
        "report": llm_report.to_dict(),
        "quality_analysis": quality_analysis.to_dict(),
        "summary": {
            "total_cell_findings": len(llm_report.cell_findings),
            "total_column_reports": len(llm_report.column_reports),
            "total_record_reports": len(llm_report.record_reports),
            "has_dataset_report": llm_report.dataset_report is not None,
            "batch_report": llm_report.batch_report_summary,
        },
    }


@router.get("/api/ai/quality-check/schema")
async def quality_check_schema():
    """Gibt das Request-Schema und verfügbare Optionen zurück."""
    return {
        "endpoint": "POST /api/ai/quality-check",
        "fields": {
            "dataset_id": "str — ID des geladenen Datensatzes (Pflicht)",
            "model": "str|null — LLM-Modell (null = Provider-Standard)",
            "columns": "list[str]|null — Spalten (null = alle nicht-leeren)",
            "levels": f"list[str] — {sorted(_VALID_LEVELS)} (Standard: cell,column)",
            "mode": f"str — {sorted(_VALID_MODES)} (Standard: pilot)",
            "sample_size": "int — Zeilenanzahl im Pilotmodus (Standard: 50)",
            "field_semantics": "dict — Spalte→Semantik (optional, für bessere Prompts)",
        },
        "issue_types": [
            "likely_correct",
            "semantic_misplacement",
            "ambiguous",
            "generic",
            "encoding_artifact",
            "review_required",
        ],
        "severity_values": ["critical", "warning", "info"],
        "suggested_actions": ["accept", "move_or_review", "flag_for_review", "correct"],
    }


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _build_profile(dataset_id: str, df, meta: dict) -> DatasetProfile:
    """Build a DatasetProfile from a stored dataset entry."""
    columns = [
        ColumnProfile(
            name=col,
            dtype=str(df[col].dtype),
            total_count=len(df),
            non_null_count=int(df[col].notna().sum()),
            unique_count=int(df[col].nunique()),
            fill_rate=round(float(df[col].notna().sum()) / len(df), 4) if len(df) > 0 else 0.0,
            sample_values=[str(v) for v in df[col].dropna().head(5).tolist()],
        )
        for col in df.columns
    ]
    return DatasetProfile(
        source_path=meta.get("source_path", dataset_id),
        source_name=meta.get("source_name", dataset_id),
        row_count=len(df),
        column_count=len(df.columns),
        columns=columns,
        id_column=meta.get("id_column"),
        encoding_detected=meta.get("encoding_detected"),
    )
