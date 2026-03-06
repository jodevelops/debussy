"""
Analysis routes: CSV ingest, dataset columns/records, NER, scan, EDTF.

Router prefix: /api
"""
from __future__ import annotations

import time
import uuid
import tempfile
from pathlib import Path

import pandas as pd

try:
    from fastapi import APIRouter, File, UploadFile
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError("pip install fastapi uvicorn python-multipart")

from kwb.api.deps import (
    ALLOWED_EXTENSIONS, MAX_CSV_COLS, MAX_CSV_ROWS, MAX_FILE_BYTES,
    MAX_UPLOAD_FILES, get_datasets, get_provider, get_workspace, get_state,
)
from kwb.ingest.csv_loader import ingest_csv
from kwb.analyze.structural import analyze_datasets
from kwb.analyze.ner import ner_hybrid, scan_problematic_terms, SYSTEM_NER
from kwb.enrich.edtf import normalize_dates, SYSTEM_EDTF
from kwb.report.markdown import render_report

router = APIRouter()


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
                .apply(lambda g: g.sample(n=max(1, int(round(len(g) * frac))), random_state=42))
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
    }


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
        suffix = Path(u.filename or "").suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            return JSONResponse({"error": f"'{u.filename}': Nur {', '.join(ALLOWED_EXTENSIONS)} erlaubt"}, 400)
        content = await u.read()
        if len(content) > MAX_FILE_BYTES:
            return JSONResponse({"error": f"'{u.filename}': Max {MAX_FILE_BYTES // (1024 * 1024)} MB"}, 400)

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tp = Path(tmp.name)
        try:
            df, pr = ingest_csv(tp)
            if len(df) > MAX_CSV_ROWS:
                return JSONResponse({"error": f"'{u.filename}': Max {MAX_CSV_ROWS:,} Zeilen"}, 400)
            if len(df.columns) > MAX_CSV_COLS:
                return JSONResponse({"error": f"'{u.filename}': Max {MAX_CSV_COLS} Spalten"}, 400)
            pr.source_name = Path(u.filename).stem
            pr.source_path = u.filename
            datasets.append((df, pr))
            state["datasets"][u.filename] = (df, pr)
            ws.source_files.append(u.filename)
        except Exception as e:
            return JSONResponse({"error": f"{u.filename}: {e}"}, 400)
        finally:
            tp.unlink(missing_ok=True)

    report = analyze_datasets(datasets)
    state["report"] = report
    return _report_json(report, render_report(report))


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
    ws.log_ai_run("ner_extract", mod or method, len(ents),
                  len([e for e in ents if e.get("confidence", 0) > 0.5]))

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

    return {
        "task_name": "NER", "total": len(ents),
        "succeeded": len([e for e in ents if e.get("confidence", 0) > 0.3]),
        "model": mod or method,
        "entities": ents[:500],
        "by_type": by_type,
        "run_metrics": metrics,
        "workspace": ws.to_summary(),
    }


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
