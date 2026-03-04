"""
Analysis routes: CSV ingest, dataset columns/records, NER, scan, EDTF.

Router prefix: /api
"""
from __future__ import annotations

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


def _report_json(report, markdown: str) -> dict:
    """Serialise an AnalysisReport for the API response."""
    from kwb.core.models import Severity
    findings = [
        f for f in report.findings
        if f.severity in (Severity.CRITICAL, Severity.WARNING)
    ]
    s = report.summary
    return {
        "total_rows": s.get("total_records", 0),
        "total_columns": s.get("total_columns", 0),
        "total_findings": s.get("total_findings", 0),
        "findings": [
            {
                "message": f.message,
                "severity": f.severity.value,
                "column": f.column,
                "record_ids": f.record_ids[:10],
            }
            for f in findings[:200]
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
async def dataset_records(name: str):
    ds = get_datasets().get(name)
    if not ds:
        return JSONResponse({"error": "Nicht geladen"}, 404)
    df, pr = ds
    id_col = pr.id_column or df.columns[0]
    ids = df[id_col].dropna().astype(str).unique().tolist()
    return {"record_ids": ids[:200]}


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
    ss = min(request.get("sample_size", 10), 500)
    syp = request.get("system_prompt", "")
    mod = request.get("model", "")
    prov = get_provider(mod)
    ws = get_workspace()

    result = ner_hybrid(
        df, cols,
        provider=prov if method != "spacy" else None,
        id_column=profile.id_column,
        sample_size=ss,
        model=mod or None,
        system_prompt=syp,
        use_spacy=(method in ("spacy", "hybrid")),
        use_llm=(method in ("llm", "hybrid")),
    )
    ents = result.to_dict_list()
    ws.add_entities(ents, replace=True)
    ws.log_ai_run("ner_extract", mod or method, len(ents),
                  len([e for e in ents if e.get("confidence", 0) > 0.5]))

    return {
        "task_name": "NER", "total": len(ents),
        "succeeded": len([e for e in ents if e.get("confidence", 0) > 0.3]),
        "model": mod or method,
        "entities": ents[:500],
        "by_type": {t.value: len(es) for t, es in result.by_type.items()},
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
    ss = min(request.get("sample_size", 20), 500)
    syp = request.get("system_prompt", "")
    mod = request.get("model", "")
    prov = get_provider(mod)
    issues, batch = scan_problematic_terms(
        df, prov,
        id_column=profile.id_column,
        sample_size=ss,
        model=mod or None,
        system_prompt=syp,
    )
    return {
        "task_name": "Scan", "total": batch.total,
        "succeeded": batch.succeeded, "model": mod or "default",
        "issues": issues[:200],
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

    ss = request.get("sample_size", 0)
    use_llm = request.get("use_llm", False)
    syp = request.get("system_prompt", "")
    mod = request.get("model", "")
    ws = get_workspace()

    mask = df[col].replace("", pd.NA).notna()
    working = df[mask]
    if ss and ss > 0 and ss < len(working):
        working = working.sample(n=ss, random_state=42)

    items = [
        {
            "record_id": str(row.get(profile.id_column, "")) if profile.id_column else "",
            "text": str(row[col]).strip(),
        }
        for _, row in working.iterrows()
        if str(row[col]).strip()
    ]

    prov = get_provider(mod) if use_llm else None
    results, batch = normalize_dates(items, provider=prov, model=mod or None, system_prompt=syp)

    ws.add_dates([
        {"original": r.original, "edtf": r.edtf, "confidence": r.confidence,
         "method": r.method, "record_id": r.record_id, "column": col}
        for r in results
    ], replace=True)

    converted = len([r for r in results if r.edtf])
    undated = len([r for r in results if not r.edtf and "undatiert" in r.note])
    failed = len(results) - converted - undated

    return {
        "task_name": "EDTF", "total": len(results),
        "converted": converted, "failed": failed, "undated": undated,
        "model": mod or "rule",
        "results": [
            {"record_id": r.record_id, "original": r.original, "edtf": r.edtf,
             "confidence": round(r.confidence, 3), "method": r.method, "note": r.note}
            for r in results
        ],
    }
