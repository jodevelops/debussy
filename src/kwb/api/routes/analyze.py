"""
Analysis routes: CSV ingest, dataset columns/records, NER, scan, EDTF,
and dictionary-based problematic-terms scan.

Router prefix: /api
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import uuid
import tempfile
from pathlib import Path

import pandas as pd

try:
    from fastapi import APIRouter, File, UploadFile
    from fastapi.responses import JSONResponse, StreamingResponse
except ImportError:
    raise ImportError("pip install fastapi uvicorn python-multipart")

from kwb.api.deps import (
    ALLOWED_EXTENSIONS, MAX_CSV_COLS, MAX_CSV_ROWS, MAX_FILE_BYTES,
    MAX_UPLOAD_FILES, get_datasets, get_provider, get_workspace, get_state,
)
from kwb.ingest.csv_loader import ingest_csv
from kwb.ingest.xlsx_loader import ingest_xlsx
from kwb.ingest.xml_loader import ingest_xml
from kwb.analyze.structural import analyze_datasets
from kwb.analyze.ner import ner_hybrid, scan_problematic_terms
from kwb.analyze.quality_report import build_quality_analysis_report
from kwb.enrich.edtf import normalize_dates
from kwb.report.markdown import render_report
from kwb.ai.prompts import PROMPT_VERSIONS

router = APIRouter()


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _apply_filters(df: pd.DataFrame, filters: dict | None) -> pd.DataFrame:
    """Apply simple API filters to a dataframe copy."""
    if not filters:
        return df
    working = df

    id_values = filters.get("record_ids")
    id_column = filters.get("id_column")
    if id_values and id_column and id_column in working.columns:
        ids = {str(v) for v in id_values if str(v).strip()}
        working = working[working[id_column].astype(str).isin(ids)]

    for rule in filters.get("where", []):
        col = rule.get("column", "")
        op = (rule.get("op", "contains") or "contains").lower()
        val = str(rule.get("value", ""))
        if col not in working.columns:
            continue
        if op == "equals":
            working = working[working[col].astype(str) == val]
        elif op == "startswith":
            working = working[working[col].astype(str).str.startswith(val, na=False)]
        else:
            working = working[working[col].astype(str).str.contains(val, na=False, case=False)]
    return working


def _build_sampling_plan(
    df: pd.DataFrame,
    request: dict,
    id_column: str | None,
    default_sample: int,
) -> tuple[pd.DataFrame, dict]:
    """Return sampled/filtered dataframe + config metadata."""
    filters = request.get("filters") or {}
    filtered = _apply_filters(df, filters)

    total_after_filter = len(filtered)
    sample_size = request.get("sample_size", default_sample)
    sample_percent = request.get("sample_percent")
    sample_mode = (request.get("sample_mode") or "random").lower()
    stratified = bool(request.get("stratified", False)) or sample_mode == "stratified"
    stratify_by = request.get("stratify_by") or id_column or ""

    if sample_percent is not None:
        target_n = max(1, int(round(total_after_filter * (float(sample_percent) / 100.0)))) if total_after_filter else 0
    elif sample_size and int(sample_size) > 0:
        target_n = min(int(sample_size), total_after_filter)
    else:
        target_n = total_after_filter

    if target_n and target_n < total_after_filter:
        if stratified and stratify_by in filtered.columns:
            frac = target_n / total_after_filter
            sampled = (
                filtered.groupby(stratify_by, group_keys=False)
                .apply(
                    lambda g: g.sample(n=max(1, int(round(len(g) * frac))), random_state=42),
                    include_groups=False,
                )
                .head(target_n)
            )
        else:
            sampled = filtered.sample(n=target_n, random_state=42)
    else:
        sampled = filtered

    return sampled, {
        "sample_mode": "stratified" if stratified else "random",
        "stratify_by": stratify_by if stratified else "",
        "requested_sample_size": sample_size,
        "sample_percent": sample_percent,
        "rows_after_filter": total_after_filter,
        "rows_selected": len(sampled),
    }


def _iter_chunks(df: pd.DataFrame, chunk_size: int):
    for start in range(0, len(df), chunk_size):
        yield (start // chunk_size) + 1, df.iloc[start:start + chunk_size]


def _estimate_eta(processed: int, total: int, elapsed: float) -> float:
    if processed <= 0 or elapsed <= 0:
        return 0.0
    speed = processed / elapsed
    remaining = max(total - processed, 0)
    return round(remaining / speed, 1) if speed > 0 else 0.0


def _persist_chunk_run(workspace, task: str, dataset: str, run_payload: dict) -> None:
    runs = workspace.extras.setdefault("chunk_runs", [])
    runs.append({"task": task, "dataset": dataset, **run_payload})
    if len(runs) > 100:
        workspace.extras["chunk_runs"] = runs[-100:]

    agg = workspace.extras.setdefault("chunk_aggregate", {})
    task_agg = agg.setdefault(task, {"runs": 0, "rows": 0, "errors": 0, "chunks": 0})
    task_agg["runs"] += 1
    task_agg["rows"] += int(run_payload.get("processed_rows", 0))
    task_agg["errors"] += int(run_payload.get("error_rows", 0))
    task_agg["chunks"] += int(run_payload.get("chunk_count", 0))
    workspace._touch()


def _report_json(report, markdown: str) -> dict:
    """Serialise an AnalysisReport for the API response."""
    s = report.summary
    datasets = [
        {
            "source_name": dp.source_name,
            "source_path": dp.source_path,
            "row_count": dp.row_count,
            "column_count": dp.column_count,
            "id_column": dp.id_column,
            "columns": [
                {
                    "name": c.name,
                    "fill_rate": c.fill_rate,
                    "unique_count": c.unique_count,
                    "sample_values": c.sample_values[:5],
                }
                for c in dp.columns
            ],
        }
        for dp in report.datasets
    ]
    return {
        "summary": {
            "total_records": s.get("total_records", 0),
            "total_columns": s.get("total_columns", 0),
            "critical": s.get("critical", 0),
            "warnings": s.get("warnings", 0),
            "info": s.get("info", 0),
        },
        "datasets": datasets,
        "findings": [
            {
                "message": f.message,
                "severity": f.severity.value,
                "category": f.category.value,
                "column": f.column,
                "suggestion": f.suggestion,
                "record_ids": f.record_ids[:10],
            }
            for f in report.findings[:200]
        ],
        "markdown": markdown,
        "quality_measures": report.quality_measures.to_dict_list() if report.quality_measures else [],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import re as _re

_COMPOSITE_KEY_RE = _re.compile(r"__\d+__\d+$")


def _normalize_upload_filename(filename: str) -> str:
    """Strip composite frontend key suffix (``__size__lastModified``) if present.

    The JS upload UI keys files internally as ``name__bytesize__lastModified``
    (e.g. ``data.csv__11565356__1768907749964``).  In normal operation the
    third argument of ``FormData.append`` ensures only the plain name reaches
    the server, but as a defensive measure we strip any such suffix here so
    that dataset lookups work regardless.
    """
    return _COMPOSITE_KEY_RE.sub("", filename)


# ---------------------------------------------------------------------------
# CSV Upload + Analyse
# ---------------------------------------------------------------------------

@router.post("/api/analyze")
async def analyze(files: list[UploadFile] = File(...)):
    """Ingest one or more CSV files and run structural analysis."""
    if len(files) > MAX_UPLOAD_FILES:
        return JSONResponse({"error": f"Maximal {MAX_UPLOAD_FILES} Dateien erlaubt"}, 400)

    state = get_state()
    state["datasets"] = {}
    ws = get_workspace()
    ws.source_files = []
    datasets = []

    for u in files:
        fname = _normalize_upload_filename(u.filename or "")
        suffix = Path(fname).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            return JSONResponse({"error": f"'{fname}': Nur {', '.join(ALLOWED_EXTENSIONS)} erlaubt"}, 400)
        content = await u.read()
        if len(content) > MAX_FILE_BYTES:
            return JSONResponse({"error": f"'{fname}': Max {MAX_FILE_BYTES // (1024 * 1024)} MB"}, 400)

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tp = Path(tmp.name)
        try:
            if suffix in {".xlsx", ".xls"}:
                df, pr = ingest_xlsx(tp)
            elif suffix == ".xml":
                df, pr = ingest_xml(tp)
            else:
                df, pr = ingest_csv(tp)
            if len(df) > MAX_CSV_ROWS:
                return JSONResponse({"error": f"'{fname}': Max {MAX_CSV_ROWS:,} Zeilen"}, 400)
            if len(df.columns) > MAX_CSV_COLS:
                return JSONResponse({"error": f"'{fname}': Max {MAX_CSV_COLS} Spalten"}, 400)
            pr.source_name = Path(fname).stem
            pr.source_path = fname
            datasets.append((df, pr))
            state["datasets"][fname] = (df, pr)
            ws.source_files.append(fname)
        except Exception as e:
            return JSONResponse({"error": f"{fname}: {e}"}, 400)
        finally:
            tp.unlink(missing_ok=True)

    report = analyze_datasets(datasets)
    state["report"] = report
    quality_report = build_quality_analysis_report(report)
    result = _report_json(report, render_report(report))
    # Structured Phase-1 quality analysis for GUI rendering
    result["quality_analysis"] = quality_report.to_dict()
    # Include auto-detected id_column candidates per dataset
    id_cols = {}
    for dp in report.datasets:
        id_cols[dp.source_name] = dp.id_column or ""
    result["id_columns"] = id_cols
    return result


@router.post("/api/dataset/{name}/set-id-column")
async def set_id_column(name: str, request: dict):
    """Set the ID column for a dataset after user selection."""
    ds = get_datasets().get(name)
    if not ds:
        return JSONResponse({"error": f"'{name}' nicht geladen"}, 404)
    df, pr = ds
    col = request.get("id_column", "")
    if col and col not in df.columns:
        return JSONResponse({"error": f"Spalte '{col}' nicht vorhanden"}, 400)
    pr.id_column = col or pr.id_column
    ws = get_workspace()
    ws.id_column = pr.id_column or ws.id_column
    ws._touch()
    # Validate uniqueness
    if col and col in df.columns:
        total = len(df)
        unique = df[col].nunique()
        is_unique = unique == total
        return {"ok": True, "id_column": col, "unique": is_unique,
                "unique_count": unique, "total": total}
    return {"ok": True, "id_column": pr.id_column}


@router.get("/api/dataset/{name}/columns")
async def dataset_columns(name: str):
    ds = get_datasets().get(name)
    if not ds:
        return JSONResponse({"error": f"'{name}' nicht geladen"}, 404)
    _, pr = ds
    return {"columns": [
        {"name": c.name, "fill_rate": c.fill_rate,
         "unique_count": c.unique_count, "sample_values": c.sample_values[:3]}
        for c in pr.columns
    ]}


@router.get("/api/dataset/{name}/records")
async def dataset_records(
    name: str,
    offset: int = 0,
    limit: int = 200,
    q: str = "",
):
    ds = get_datasets().get(name)
    if not ds:
        return JSONResponse({"error": "Nicht geladen"}, 404)
    df, pr = ds
    id_col = pr.id_column or df.columns[0]
    ids = df[id_col].dropna().astype(str).unique().tolist()
    if q:
        ids = [rid for rid in ids if q.lower() in rid.lower()]
    total = len(ids)
    safe_offset = max(offset, 0)
    safe_limit = max(1, min(limit, 2000))
    return {
        "record_ids": ids[safe_offset:safe_offset + safe_limit],
        "offset": safe_offset,
        "limit": safe_limit,
        "total": total,
        "has_more": (safe_offset + safe_limit) < total,
        "filter": {"q": q},
    }


# ---------------------------------------------------------------------------
# NER
# ---------------------------------------------------------------------------

@router.post("/api/ner")
async def api_ner(request: dict):
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds
    cols = request.get("columns", [])
    if not cols:
        cols = [c for c in df.columns if df[c].dtype == object]
    method = request.get("method", "llm")
    ss = min(int(request.get("sample_size", 10) or 10), max(len(df), 1))
    chunk_size = max(1, min(int(request.get("chunk_size", 200) or 200), 1000))
    syp = request.get("system_prompt", "")
    mod = request.get("model", "")
    prov = get_provider(mod)
    ws = get_workspace()

    # Feature 9: Configurable entity types
    entity_types = request.get("entity_types", [])

    working, sampling = _build_sampling_plan(df, request, profile.id_column, ss)
    started = time.perf_counter()
    all_entities = []
    errors = 0
    chunk_reports = []
    for chunk_no, chunk_df in _iter_chunks(working, chunk_size):
        try:
            chunk_result = ner_hybrid(
                chunk_df, cols,
                provider=prov if method != "spacy" else None,
                id_column=profile.id_column,
                sample_size=None,
                model=mod or None,
                system_prompt=syp,
                use_spacy=(method in ("spacy", "hybrid")),
                use_llm=(method in ("llm", "hybrid")),
                entity_types=entity_types or None,
            )
            all_entities.extend(chunk_result.to_dict_list(deduplicated=False))
            chunk_reports.append({
                "chunk": chunk_no,
                "rows": len(chunk_df),
                "entities": len(chunk_result.entities),
            })
        except Exception:
            errors += len(chunk_df)
            chunk_reports.append({"chunk": chunk_no, "rows": len(chunk_df), "error": True})

    # Filter by entity_types if specified
    if entity_types:
        all_entities = [e for e in all_entities if e.get("type") in entity_types]

    # preserve current API format from deduplicated dicts
    dedup = {}
    for e in all_entities:
        key = f"{str(e.get('text','')).strip().lower()}||{e.get('type','CON')}"
        if key not in dedup or float(e.get("confidence", 0)) > float(dedup[key].get("confidence", 0)):
            dedup[key] = e
    ents = list(dedup.values())
    by_type = {}
    for e in ents:
        etype = e.get("type", "CON")
        by_type[etype] = by_type.get(etype, 0) + 1
    ws.add_entities(ents, replace=True)

    # Feature 7: AI result provenance metadata
    model_name = mod or method
    prompt_name = "entity_extraction_normdata"
    prompt_version = PROMPT_VERSIONS.get("entity_extraction_normdata", "1.0.0")
    ws.log_ai_run(
        "ner_extract", model_name, len(ents),
        len([e for e in ents if e.get("confidence", 0) > 0.5]),
        prompt_name=prompt_name,
        prompt_version=prompt_version,
    )

    elapsed = max(time.perf_counter() - started, 0.001)
    metrics = {
        "processed_rows": len(working),
        "total_rows": len(df),
        "error_rows": errors,
        "error_rate": round(errors / len(working), 4) if len(working) else 0,
        "elapsed_seconds": round(elapsed, 2),
        "eta_seconds": _estimate_eta(len(working), len(df), elapsed),
        "chunk_count": len(chunk_reports),
        "chunks": chunk_reports,
        "sampling": sampling,
    }
    _persist_chunk_run(ws, "ner", dsn, {
        "run_id": str(uuid.uuid4()),
        **metrics,
    })

    # Feature 7: Include AI provenance in response
    ai_provenance = {
        "model": model_name,
        "prompt_name": prompt_name,
        "prompt_version": prompt_version,
        "entity_types_requested": entity_types or "all",
    }

    return {
        "task_name": "NER", "total": len(ents),
        "prompt_name": prompt_name,
        "prompt_version": prompt_version,
        "succeeded": len([e for e in ents if e.get("confidence", 0) > 0.3]),
        "model": model_name,
        "entities": ents[:500],
        "by_type": by_type,
        "run_metrics": metrics,
        "ai_provenance": ai_provenance,
        "workspace": ws.to_summary(),
    }


# ---------------------------------------------------------------------------
# NER — SSE streaming
# ---------------------------------------------------------------------------

@router.post("/api/ner/stream")
async def api_ner_stream(request: dict):
    """SSE streaming version of /api/ner — yields progress per chunk."""
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds
    cols = request.get("columns", [])
    if not cols:
        cols = [c for c in df.columns if df[c].dtype == object]
    method = request.get("method", "llm")
    ss = min(int(request.get("sample_size", 10) or 10), max(len(df), 1))
    chunk_size = max(1, min(int(request.get("chunk_size", 200) or 200), 1000))
    syp = request.get("system_prompt", "")
    mod = request.get("model", "")
    prov = get_provider(mod)
    ws = get_workspace()
    entity_types = request.get("entity_types", [])
    working, sampling = _build_sampling_plan(df, request, profile.id_column, ss)

    total_chunks = max(1, -(-len(working) // chunk_size))  # ceil division

    async def generate():
        started = time.perf_counter()
        all_entities = []
        errors = 0
        chunk_reports = []
        for chunk_no, chunk_df in _iter_chunks(working, chunk_size):
            try:
                chunk_result = ner_hybrid(
                    chunk_df, cols,
                    provider=prov if method != "spacy" else None,
                    id_column=profile.id_column,
                    sample_size=None,
                    model=mod or None,
                    system_prompt=syp,
                    use_spacy=(method in ("spacy", "hybrid")),
                    use_llm=(method in ("llm", "hybrid")),
                    entity_types=entity_types or None,
                )
                new_ents = chunk_result.to_dict_list(deduplicated=False)
                all_entities.extend(new_ents)
                chunk_reports.append({
                    "chunk": chunk_no, "rows": len(chunk_df),
                    "entities": len(chunk_result.entities),
                })
            except Exception:
                errors += len(chunk_df)
                chunk_reports.append({
                    "chunk": chunk_no, "rows": len(chunk_df), "error": True,
                })

            yield _sse_event({
                "type": "progress", "chunk": chunk_no,
                "total_chunks": total_chunks,
                "entities_so_far": len(all_entities),
            })

        # Deduplicate + build final result (same logic as api_ner)
        if entity_types:
            all_entities = [e for e in all_entities if e.get("type") in entity_types]
        dedup = {}
        for e in all_entities:
            key = f"{str(e.get('text','')).strip().lower()}||{e.get('type','CON')}"
            if key not in dedup or float(e.get("confidence", 0)) > float(
                dedup[key].get("confidence", 0)
            ):
                dedup[key] = e
        ents = list(dedup.values())
        by_type = {}
        for e in ents:
            etype = e.get("type", "CON")
            by_type[etype] = by_type.get(etype, 0) + 1
        ws.add_entities(ents, replace=True)

        model_name = mod or method
        prompt_name = "entity_extraction_normdata"
        prompt_version = PROMPT_VERSIONS.get("entity_extraction_normdata", "1.0.0")
        ws.log_ai_run(
            "ner_extract", model_name, len(ents),
            len([e for e in ents if e.get("confidence", 0) > 0.5]),
            prompt_name=prompt_name, prompt_version=prompt_version,
        )

        elapsed = max(time.perf_counter() - started, 0.001)
        metrics = {
            "processed_rows": len(working), "total_rows": len(df),
            "error_rows": errors,
            "error_rate": round(errors / len(working), 4) if len(working) else 0,
            "elapsed_seconds": round(elapsed, 2),
            "eta_seconds": _estimate_eta(len(working), len(df), elapsed),
            "chunk_count": len(chunk_reports), "chunks": chunk_reports,
            "sampling": sampling,
        }
        _persist_chunk_run(ws, "ner", dsn, {
            "run_id": str(uuid.uuid4()), **metrics,
        })
        ai_provenance = {
            "model": model_name, "prompt_name": prompt_name,
            "prompt_version": prompt_version,
            "entity_types_requested": entity_types or "all",
        }
        yield _sse_event({
            "type": "done",
            "result": {
                "task_name": "NER", "total": len(ents),
                "prompt_name": prompt_name, "prompt_version": prompt_version,
                "succeeded": len([e for e in ents if e.get("confidence", 0) > 0.3]),
                "model": model_name,
                "entities": ents[:500], "by_type": by_type,
                "run_metrics": metrics, "ai_provenance": ai_provenance,
                "workspace": ws.to_summary(),
            },
        })

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Scan (problematic terms)
# ---------------------------------------------------------------------------

@router.post("/api/scan")
async def api_scan(request: dict):
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds
    ss = min(int(request.get("sample_size", 20) or 20), max(len(df), 1))
    chunk_size = max(1, min(int(request.get("chunk_size", 200) or 200), 1000))
    syp = request.get("system_prompt", "")
    mod = request.get("model", "")
    prov = get_provider(mod)
    working, sampling = _build_sampling_plan(df, request, profile.id_column, ss)
    started = time.perf_counter()
    issues, errors, batches = [], 0, []
    for chunk_no, chunk_df in _iter_chunks(working, chunk_size):
        try:
            i2, batch = scan_problematic_terms(
                chunk_df, prov,
                id_column=profile.id_column,
                sample_size=len(chunk_df),
                model=mod or None,
                system_prompt=syp,
            )
            issues.extend(i2)
            batches.append({"chunk": chunk_no, "rows": len(chunk_df), "issues": len(i2), "succeeded": batch.succeeded})
        except Exception:
            errors += len(chunk_df)
            batches.append({"chunk": chunk_no, "rows": len(chunk_df), "error": True})

    elapsed = max(time.perf_counter() - started, 0.001)
    metrics = {
        "processed_rows": len(working), "total_rows": len(df),
        "error_rows": errors, "error_rate": round(errors / len(working), 4) if len(working) else 0,
        "elapsed_seconds": round(elapsed, 2), "eta_seconds": _estimate_eta(len(working), len(df), elapsed),
        "chunk_count": len(batches), "chunks": batches, "sampling": sampling,
    }
    ws = get_workspace()
    _persist_chunk_run(ws, "scan", dsn, {"run_id": str(uuid.uuid4()), **metrics})

    succeeded = sum(b.get("succeeded", 0) for b in batches)
    return {
        "task_name": "Scan", "total": len(working),
        "succeeded": succeeded, "model": mod or "default",
        "issues": issues[:200],
        "run_metrics": metrics,
    }


# ---------------------------------------------------------------------------
# Scan — SSE streaming
# ---------------------------------------------------------------------------

@router.post("/api/scan/stream")
async def api_scan_stream(request: dict):
    """SSE streaming version of /api/scan — yields progress per chunk."""
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds
    ss = min(int(request.get("sample_size", 20) or 20), max(len(df), 1))
    chunk_size = max(1, min(int(request.get("chunk_size", 200) or 200), 1000))
    syp = request.get("system_prompt", "")
    mod = request.get("model", "")
    prov = get_provider(mod)
    working, sampling = _build_sampling_plan(df, request, profile.id_column, ss)

    total_chunks = max(1, -(-len(working) // chunk_size))

    async def generate():
        started = time.perf_counter()
        issues, errors, batches = [], 0, []
        for chunk_no, chunk_df in _iter_chunks(working, chunk_size):
            try:
                i2, batch = scan_problematic_terms(
                    chunk_df, prov,
                    id_column=profile.id_column,
                    sample_size=len(chunk_df),
                    model=mod or None,
                    system_prompt=syp,
                )
                issues.extend(i2)
                batches.append({
                    "chunk": chunk_no, "rows": len(chunk_df),
                    "issues": len(i2), "succeeded": batch.succeeded,
                })
            except Exception:
                errors += len(chunk_df)
                batches.append({
                    "chunk": chunk_no, "rows": len(chunk_df), "error": True,
                })

            yield _sse_event({
                "type": "progress", "chunk": chunk_no,
                "total_chunks": total_chunks,
                "issues_so_far": len(issues),
            })

        elapsed = max(time.perf_counter() - started, 0.001)
        metrics = {
            "processed_rows": len(working), "total_rows": len(df),
            "error_rows": errors,
            "error_rate": round(errors / len(working), 4) if len(working) else 0,
            "elapsed_seconds": round(elapsed, 2),
            "eta_seconds": _estimate_eta(len(working), len(df), elapsed),
            "chunk_count": len(batches), "chunks": batches,
            "sampling": sampling,
        }
        ws = get_workspace()
        _persist_chunk_run(ws, "scan", dsn, {
            "run_id": str(uuid.uuid4()), **metrics,
        })
        succeeded = sum(b.get("succeeded", 0) for b in batches)
        yield _sse_event({
            "type": "done",
            "result": {
                "task_name": "Scan", "total": len(working),
                "succeeded": succeeded, "model": mod or "default",
                "issues": issues[:200], "run_metrics": metrics,
            },
        })

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# EDTF
# ---------------------------------------------------------------------------

@router.post("/api/edtf")
async def api_edtf(request: dict):
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds
    col = request.get("column", "")
    if not col:
        return JSONResponse({"error": "Spalte wählen"}, 400)
    if col not in df.columns:
        return JSONResponse({"error": f"Spalte '{col}' nicht vorhanden"}, 400)

    ss = int(request.get("sample_size", 0) or 0)
    chunk_size = max(1, min(int(request.get("chunk_size", 200) or 200), 1000))
    use_llm = request.get("use_llm", False)
    syp = request.get("system_prompt", "")
    mod = request.get("model", "")
    ws = get_workspace()

    mask = df[col].replace("", pd.NA).notna()
    source_df = df[mask]
    working, sampling = _build_sampling_plan(source_df, request, profile.id_column, ss)

    prov = get_provider(mod) if use_llm else None
    started = time.perf_counter()
    all_results = []
    chunk_reports = []
    errors = 0
    for chunk_no, chunk_df in _iter_chunks(working, chunk_size):
        items = [
            {
                "record_id": str(row.get(profile.id_column, "")) if profile.id_column else "",
                "text": str(row[col]).strip(),
            }
            for _, row in chunk_df.iterrows()
            if str(row[col]).strip()
        ]
        try:
            results, _batch = normalize_dates(items, provider=prov, model=mod or None, system_prompt=syp)
            all_results.extend(results)
            chunk_reports.append({"chunk": chunk_no, "rows": len(chunk_df), "results": len(results)})
        except Exception:
            errors += len(chunk_df)
            chunk_reports.append({"chunk": chunk_no, "rows": len(chunk_df), "error": True})
    results = all_results

    ws.add_dates([
        {"original": r.original, "edtf": r.edtf, "confidence": r.confidence,
         "method": r.method, "record_id": r.record_id, "column": col}
        for r in results
    ], replace=True)

    converted = len([r for r in results if r.edtf])
    undated = len([r for r in results if not r.edtf and "undatiert" in r.note])
    failed = len(results) - converted - undated
    elapsed = max(time.perf_counter() - started, 0.001)
    metrics = {
        "processed_rows": len(working), "total_rows": len(source_df),
        "error_rows": errors, "error_rate": round(errors / len(working), 4) if len(working) else 0,
        "elapsed_seconds": round(elapsed, 2), "eta_seconds": _estimate_eta(len(working), len(source_df), elapsed),
        "chunk_count": len(chunk_reports), "chunks": chunk_reports, "sampling": sampling,
    }
    _persist_chunk_run(ws, "edtf", dsn, {"run_id": str(uuid.uuid4()), **metrics})

    return {
        "task_name": "EDTF", "total": len(results),
        "converted": converted, "failed": failed, "undated": undated,
        "model": mod or "rule",
        "run_metrics": metrics,
        "results": [
            {"record_id": r.record_id, "original": r.original, "edtf": r.edtf,
             "confidence": round(r.confidence, 3), "method": r.method, "note": r.note}
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# EDTF — SSE streaming
# ---------------------------------------------------------------------------

@router.post("/api/edtf/stream")
async def api_edtf_stream(request: dict):
    """SSE streaming version of /api/edtf — yields progress per chunk."""
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds
    col = request.get("column", "")
    if not col:
        return JSONResponse({"error": "Spalte wählen"}, 400)
    if col not in df.columns:
        return JSONResponse({"error": f"Spalte '{col}' nicht vorhanden"}, 400)

    ss = int(request.get("sample_size", 0) or 0)
    chunk_size = max(1, min(int(request.get("chunk_size", 200) or 200), 1000))
    use_llm = request.get("use_llm", False)
    syp = request.get("system_prompt", "")
    mod = request.get("model", "")
    ws = get_workspace()

    mask = df[col].replace("", pd.NA).notna()
    source_df = df[mask]
    working, sampling = _build_sampling_plan(source_df, request, profile.id_column, ss)
    prov = get_provider(mod) if use_llm else None

    total_chunks = max(1, -(-len(working) // chunk_size))

    async def generate():
        started = time.perf_counter()
        all_results = []
        chunk_reports = []
        errors = 0
        for chunk_no, chunk_df in _iter_chunks(working, chunk_size):
            items = [
                {
                    "record_id": (
                        str(row.get(profile.id_column, "")) if profile.id_column else ""
                    ),
                    "text": str(row[col]).strip(),
                }
                for _, row in chunk_df.iterrows()
                if str(row[col]).strip()
            ]
            try:
                results, _batch = normalize_dates(
                    items, provider=prov, model=mod or None, system_prompt=syp,
                )
                all_results.extend(results)
                chunk_reports.append({
                    "chunk": chunk_no, "rows": len(chunk_df),
                    "results": len(results),
                })
            except Exception:
                errors += len(chunk_df)
                chunk_reports.append({
                    "chunk": chunk_no, "rows": len(chunk_df), "error": True,
                })

            yield _sse_event({
                "type": "progress", "chunk": chunk_no,
                "total_chunks": total_chunks,
                "results_so_far": len(all_results),
            })

        results = all_results
        ws.add_dates([
            {"original": r.original, "edtf": r.edtf, "confidence": r.confidence,
             "method": r.method, "record_id": r.record_id, "column": col}
            for r in results
        ], replace=True)

        converted = len([r for r in results if r.edtf])
        undated = len([r for r in results if not r.edtf and "undatiert" in r.note])
        failed = len(results) - converted - undated
        elapsed = max(time.perf_counter() - started, 0.001)
        metrics = {
            "processed_rows": len(working), "total_rows": len(source_df),
            "error_rows": errors,
            "error_rate": round(errors / len(working), 4) if len(working) else 0,
            "elapsed_seconds": round(elapsed, 2),
            "eta_seconds": _estimate_eta(len(working), len(source_df), elapsed),
            "chunk_count": len(chunk_reports), "chunks": chunk_reports,
            "sampling": sampling,
        }
        _persist_chunk_run(ws, "edtf", dsn, {
            "run_id": str(uuid.uuid4()), **metrics,
        })
        yield _sse_event({
            "type": "done",
            "result": {
                "task_name": "EDTF", "total": len(results),
                "converted": converted, "failed": failed, "undated": undated,
                "model": mod or "rule", "run_metrics": metrics,
                "results": [
                    {"record_id": r.record_id, "original": r.original,
                     "edtf": r.edtf, "confidence": round(r.confidence, 3),
                     "method": r.method, "note": r.note}
                    for r in results
                ],
            },
        })

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Problematische Begriffe — Dictionary-based (1:1 matching)
# ---------------------------------------------------------------------------

@router.get("/api/problematic-terms")
async def get_problematic_terms():
    """Return the current problematic-terms dictionary."""
    ws = get_workspace()
    terms = ws.extras.get("problematic_terms", [])
    return {"terms": terms, "count": len(terms)}


@router.post("/api/problematic-terms")
async def add_problematic_term(request: dict):
    """Add a single term to the problematic-terms dictionary."""
    ws = get_workspace()
    terms_list = ws.extras.setdefault("problematic_terms", [])
    new_term = (request.get("term") or "").strip()
    if not new_term:
        return JSONResponse({"error": "Kein Begriff angegeben"}, 400)
    existing = {t["term"].lower() for t in terms_list}
    if new_term.lower() in existing:
        return JSONResponse({"error": "Begriff bereits vorhanden"}, 409)
    terms_list.append({
        "term": new_term,
        "replacement": (request.get("replacement") or "").strip(),
        "category": (request.get("category") or "").strip(),
        "note": (request.get("note") or "").strip(),
    })
    ws._touch()
    return {"terms": terms_list, "count": len(terms_list)}


@router.delete("/api/problematic-terms/{term_idx}")
async def delete_problematic_term(term_idx: int):
    """Remove a term by index from the problematic-terms dictionary."""
    ws = get_workspace()
    terms_list = ws.extras.get("problematic_terms", [])
    if term_idx < 0 or term_idx >= len(terms_list):
        return JSONResponse({"error": "Index ungültig"}, 400)
    removed = terms_list.pop(term_idx)
    ws._touch()
    return {"removed": removed, "count": len(terms_list)}


@router.post("/api/dict-upload")
async def upload_problematic_dict(file: UploadFile = File(...)):
    """
    Upload a CSV or JSON file as the problematic-terms dictionary.
    CSV format: term[,replacement[,category[,note]]] — first row optionally a header.
    JSON format: list of strings, list of {term, replacement, category, note}, or
                 dict of {term: replacement}.
    """
    content = await file.read()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".json", ".txt"}:
        return JSONResponse({"error": "Nur CSV, JSON oder TXT erlaubt"}, 400)

    ws = get_workspace()
    terms_list = ws.extras.setdefault("problematic_terms", [])
    existing = {t["term"].lower() for t in terms_list}
    new_terms: list[dict] = []

    try:
        if suffix == ".json":
            data = json.loads(content.decode("utf-8-sig"))
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        t = item.strip()
                        entry = {"term": t, "replacement": "", "category": "", "note": ""}
                    elif isinstance(item, dict):
                        t = (item.get("term") or "").strip()
                        entry = {
                            "term": t,
                            "replacement": (item.get("replacement") or item.get("ersatz") or "").strip(),
                            "category": (item.get("category") or item.get("kategorie") or "").strip(),
                            "note": (item.get("note") or item.get("hinweis") or "").strip(),
                        }
                    else:
                        continue
                    if t and t.lower() not in existing:
                        new_terms.append(entry)
                        existing.add(t.lower())
            elif isinstance(data, dict):
                for term, info in data.items():
                    t = term.strip()
                    if not t or t.lower() in existing:
                        continue
                    if isinstance(info, dict):
                        entry = {
                            "term": t,
                            "replacement": (info.get("replacement") or "").strip(),
                            "category": (info.get("category") or "").strip(),
                            "note": (info.get("note") or "").strip(),
                        }
                    else:
                        entry = {"term": t, "replacement": str(info or ""), "category": "", "note": ""}
                    new_terms.append(entry)
                    existing.add(t.lower())
        else:
            # CSV or TXT — one term per line or CSV columns
            text = content.decode("utf-8-sig")
            reader = csv.reader(io.StringIO(text))
            first_row = True
            for row in reader:
                if not row:
                    continue
                t = row[0].strip()
                if not t:
                    continue
                # Skip header row if it looks like a header
                if first_row and t.lower() in {"term", "begriff", "wort", "word"}:
                    first_row = False
                    continue
                first_row = False
                repl = row[1].strip() if len(row) > 1 else ""
                cat = row[2].strip() if len(row) > 2 else ""
                note = row[3].strip() if len(row) > 3 else ""
                if t.lower() not in existing:
                    new_terms.append({"term": t, "replacement": repl, "category": cat, "note": note})
                    existing.add(t.lower())
    except Exception as e:
        return JSONResponse({"error": f"Datei konnte nicht gelesen werden: {e}"}, 400)

    terms_list.extend(new_terms)
    ws._touch()
    return {"added": len(new_terms), "total": len(terms_list), "terms": terms_list}


@router.post("/api/dict-scan")
async def dict_scan(request: dict):
    """
    Scan a dataset for terms in the problematic-terms dictionary (1:1 matching).
    Optionally also scans OCR text from image analyses.
    """
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds

    ws = get_workspace()
    terms_list = ws.extras.get("problematic_terms", [])
    if not terms_list:
        return JSONResponse({"error": "Wörterbuch ist leer. Bitte zuerst Begriffe hinzufügen."}, 400)

    include_cols = request.get("columns") or [c for c in df.columns if df[c].dtype == object]
    scan_ocr = bool(request.get("scan_ocr", False))
    case_sensitive = bool(request.get("case_sensitive", False))
    whole_word = bool(request.get("whole_word", True))

    # Build lookup: term_lower → entry
    term_lookup: dict[str, dict] = {}
    for entry in terms_list:
        t = (entry.get("term") or "").strip()
        if t:
            key = t if case_sensitive else t.lower()
            term_lookup[key] = entry

    id_col = profile.id_column or (df.columns[0] if len(df.columns) > 0 else "")
    matches: list[dict] = []

    for _, row in df.iterrows():
        raw_id = row[id_col] if id_col and id_col in row.index else None
        record_id = "" if raw_id is None or pd.isna(raw_id) else str(raw_id)
        for col in include_cols:
            if col not in df.columns:
                continue
            raw_val = row.get(col)
            cell_val = "" if raw_val is None or pd.isna(raw_val) else str(raw_val)
            if not cell_val or cell_val == "nan":
                continue
            cell_cmp = cell_val if case_sensitive else cell_val.lower()
            for term_key, entry in term_lookup.items():
                if whole_word:
                    pattern = r"(?<![^\s,;.!?\"'()\[\]])" + re.escape(term_key) + r"(?![^\s,;.!?\"'()\[\]])"
                    found = bool(re.search(pattern, cell_cmp))
                else:
                    found = term_key in cell_cmp
                if found:
                    matches.append({
                        "term": entry["term"],
                        "cell_value": cell_val[:300],
                        "column": col,
                        "record_id": record_id,
                        "replacement": entry.get("replacement", ""),
                        "category": entry.get("category", ""),
                        "note": entry.get("note", ""),
                    })

    # Optionally scan OCR text from image analyses
    if scan_ocr and ws.image_analyses:
        for analysis in ws.image_analyses:
            if not analysis.result:
                continue
            text = (analysis.result.get("transcription") or
                    analysis.result.get("text") or "")
            if not text:
                continue
            text_cmp = text if case_sensitive else text.lower()
            for term_key, entry in term_lookup.items():
                if whole_word:
                    pattern = r"(?<![^\s,;.!?\"'()\[\]])" + re.escape(term_key) + r"(?![^\s,;.!?\"'()\[\]])"
                    found = bool(re.search(pattern, text_cmp))
                else:
                    found = term_key in text_cmp
                if found:
                    matches.append({
                        "term": entry["term"],
                        "cell_value": text[:300],
                        "column": f"[OCR] {analysis.filename}",
                        "record_id": analysis.record_id or analysis.image_id,
                        "replacement": entry.get("replacement", ""),
                        "category": entry.get("category", ""),
                        "note": entry.get("note", ""),
                    })

    return {
        "total_matches": len(matches),
        "terms_checked": len(terms_list),
        "records_scanned": len(df),
        "matches": matches[:2000],
        "dataset": dsn,
    }


# ---------------------------------------------------------------------------
# NER Review Gate — spot-check, auto-accept, single review
# ---------------------------------------------------------------------------

@router.post("/api/ner/review/sample")
async def ner_review_sample(request: dict):
    """Return a spot-check sample of pending NER entities for review."""
    from kwb.core.workspace import ReviewStatus
    ws = get_workspace()
    sample_size = min(request.get("sample_size", 20), 200)
    strategy = request.get("strategy", "random")
    entity_type = request.get("entity_type", "")

    pending = [
        (i, e) for i, e in enumerate(ws.entity_reviews)
        if e.status == ReviewStatus.PENDING
        and (not entity_type or e.entity_type == entity_type)
    ]
    total_pending = len(pending)

    if strategy == "low_confidence":
        pending.sort(key=lambda t: t[1].confidence)
    elif strategy == "by_type":
        pending.sort(key=lambda t: t[1].entity_type)
    else:
        import random
        random.shuffle(pending)

    sample = pending[:sample_size]
    return {
        "sample": [
            {"index": i, **e.to_dict()} for i, e in sample
        ],
        "total_pending": total_pending,
        "sample_size": len(sample),
        "strategy": strategy,
    }


@router.post("/api/ner/review/auto-accept")
async def ner_review_auto_accept(request: dict):
    """Auto-accept all NER entities with confidence >= min_confidence."""
    from kwb.core.workspace import ReviewStatus
    ws = get_workspace()
    min_confidence = float(request.get("min_confidence", 0.8))
    entity_types = request.get("entity_types", [])

    auto_accepted = 0
    for er in ws.entity_reviews:
        if er.status != ReviewStatus.PENDING:
            continue
        if entity_types and er.entity_type not in entity_types:
            continue
        if er.confidence >= min_confidence:
            er.accept(
                note=f"Auto-accepted (confidence {er.confidence:.2f} >= {min_confidence})",
            )
            auto_accepted += 1

    remaining = sum(
        1 for e in ws.entity_reviews if e.status == ReviewStatus.PENDING
    )
    return {
        "auto_accepted": auto_accepted,
        "remaining_pending": remaining,
        "min_confidence": min_confidence,
    }


@router.post("/api/ner/review/{index}")
async def ner_review_single(index: int, request: dict):
    """Review a single NER entity by index."""
    ws = get_workspace()
    if index < 0 or index >= len(ws.entity_reviews):
        return JSONResponse({"error": "Index ungültig"}, 400)

    updates = {}
    for key in ("status", "entity_type", "text", "reviewer_note", "editor_note"):
        if key in request:
            updates[key] = request[key]

    ws.update_entity(index, updates)
    return {"ok": True, "entity": ws.entity_reviews[index].to_dict()}
