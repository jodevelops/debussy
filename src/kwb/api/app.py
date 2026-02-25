"""
Debussy v0.5 — KI-gestützte Kuratierungswerkbank.
PYTHONPATH=src python -m kwb.api.app → http://localhost:8765
"""
from __future__ import annotations
import json, sys, tempfile, time
from pathlib import Path
from typing import Any
import pandas as pd

try:
    from fastapi import FastAPI, UploadFile, File
    from fastapi.responses import HTMLResponse, JSONResponse
    import uvicorn
except ImportError:
    print("pip install fastapi uvicorn python-multipart"); sys.exit(1)

from kwb.core.config import load_config
from kwb.core.models import Severity
from kwb.core.workspace import Workspace
from kwb.ingest.csv_loader import ingest_csv
from kwb.analyze.structural import analyze_datasets
from kwb.analyze.semantic import classify_subjects
from kwb.analyze.ner import ner_hybrid, scan_problematic_terms, SYSTEM_NER
from kwb.enrich.edtf import normalize_dates, normalize_date_rules, SYSTEM_EDTF
from kwb.enrich.gnd import gnd_search, gnd_batch_search
from kwb.export.goobi_xml import export_goobi_xml, export_goobi_batch
from kwb.ai.provider import AIMessage
from kwb.ai.gpustack import GPUStackProvider
from kwb.ai.mock import MockProvider
from kwb.ai.batch import process_batch, _try_parse_json, BatchReport
from kwb.ai.prompts import (
    SYSTEM_METADATA_EXPERT_DE, SYSTEM_METADATA_EXPERT_EN,
    SYSTEM_VISION_EXPERT_DE, NER_CATEGORIES,
)
from kwb.report.markdown import render_report

app = FastAPI(title="Debussy", version="0.5.0")
_state: dict[str, Any] = {
    "datasets": {},
    "report": None,
    "config": None,
    "workspace": Workspace(name="default"),
}
_HTML_DIR = Path(__file__).parent

def _cfg():
    if _state["config"] is None: _state["config"] = load_config()
    return _state["config"]

def _prov(model: str = ""):
    c = _cfg()
    if c.is_gpustack_configured:
        pc = c.to_provider_config()
        if model: pc.default_model = model
        return GPUStackProvider(pc)
    return MockProvider.with_defaults()

def _ws() -> Workspace: return _state["workspace"]

# ---------------------------------------------------------------------------
# JSON injected into HTML
# ---------------------------------------------------------------------------
PRESETS = {
    "meta_de": SYSTEM_METADATA_EXPERT_DE,
    "meta_en": SYSTEM_METADATA_EXPERT_EN,
    "vision_de": SYSTEM_VISION_EXPERT_DE,
    "ner_de": SYSTEM_NER,
    "edtf_de": SYSTEM_EDTF,
    "scan_de": "Du bist ein Experte fuer Metadatenqualitaet. Identifiziere veraltete, koloniale oder problematische Begriffe. Antworte als JSON.",
    "custom": "",
}

TASKS_UI = {
    "ner": {"name": "Named Entity Recognition", "type": "NER",
            "description": "Erkennt Personen, Orte, Organisationen etc. (SpaCy+LLM)"},
    "scan": {"name": "Problematische Begriffe", "type": "Scan",
             "description": "Durchsucht Datenset nach veralteten/koloniale Terminologie"},
    "edtf": {"name": "EDTF-Normalisierung", "type": "EDTF",
             "description": "Datumsangaben → LOC Extended Date/Time Format"},
    "gnd": {"name": "GND-Lookup", "type": "GND",
            "description": "Echte GND-IDs via lobid.org API (kein KI-Raten)"},
    "classify": {"name": "Schlagwort-Klassifikation", "type": "KI",
                 "description": "Klassifiziert Subjects in NER-Kategorien"},
    "describe": {"name": "Spalten-Beschreibungen", "type": "KI",
                 "description": "KI-generierte Inhaltsbeschreibungen"},
    "export": {"name": "Goobi-XML-Export", "type": "Export",
               "description": "Export im goobi-import Format mit kuratierten Entities"},
}

CATALOG = [
    {"id":"I-01","name":"CSV-Import","module":"Ingest","status":"done","status_label":"Aktiv","tests":"TestIngest","note":"Encoding-Erkennung"},
    {"id":"I-02","name":"Datei-Selektion","module":"Ingest","status":"done","status_label":"Aktiv","tests":"GUI","note":"Checkbox"},
    {"id":"I-03","name":"Bild-Import","module":"Ingest","status":"done","status_label":"Aktiv","tests":"TestImageLoader","note":"EXIF"},
    {"id":"A-01","name":"Fehlende Werte","module":"Analyse","status":"done","status_label":"Aktiv","tests":"TestAnalysis","note":""},
    {"id":"A-02","name":"Duplikate","module":"Analyse","status":"done","status_label":"Aktiv","tests":"TestAnalysis","note":""},
    {"id":"A-03","name":"Encoding","module":"Analyse","status":"done","status_label":"Aktiv","tests":"TestAnalysis","note":""},
    {"id":"A-04","name":"Format-Inkonsistenzen","module":"Analyse","status":"done","status_label":"Aktiv","tests":"TestAnalysis","note":""},
    {"id":"A-05","name":"Term-Varianten","module":"Analyse","status":"done","status_label":"Aktiv","tests":"TestAnalysis","note":""},
    {"id":"A-06","name":"Cross-File-Linkage","module":"Analyse","status":"done","status_label":"Aktiv","tests":"TestIntegration","note":""},
    {"id":"A-07","name":"GND-Abdeckung","module":"Analyse","status":"done","status_label":"Aktiv","tests":"TestAnalysis","note":""},
    {"id":"N-01","name":"NER (LLM)","module":"NER","status":"done","status_label":"Aktiv","tests":"TestNERWithMock","note":"10 Entity-Typen"},
    {"id":"N-02","name":"NER (SpaCy)","module":"NER","status":"done","status_label":"Aktiv","tests":"Import-Test","note":"Optional"},
    {"id":"N-03","name":"NER Hybrid","module":"NER","status":"done","status_label":"Aktiv","tests":"test_hybrid","note":"SpaCy+LLM"},
    {"id":"N-04","name":"Problematische Begriffe","module":"NER","status":"done","status_label":"Aktiv","tests":"test_scan","note":"Fullscan"},
    {"id":"N-05","name":"Entity-Editor","module":"NER","status":"partial","status_label":"Teilweise","tests":"GUI","note":"Accept/Reject in Workspace"},
    {"id":"E-01","name":"EDTF Regeln","module":"EDTF","status":"done","status_label":"Aktiv","tests":"TestEDTFRules (17)","note":""},
    {"id":"E-02","name":"EDTF LLM-Fallback","module":"EDTF","status":"done","status_label":"Aktiv","tests":"TestEDTFHybrid","note":""},
    {"id":"E-03","name":"EDTF in GUI","module":"EDTF","status":"done","status_label":"Aktiv","tests":"GUI","note":""},
    {"id":"G-01","name":"GND-Lookup (live)","module":"Enrich","status":"done","status_label":"Aktiv","tests":"TestGNDModule","note":"lobid.org API"},
    {"id":"G-02","name":"GND Batch","module":"Enrich","status":"done","status_label":"Aktiv","tests":"TestGNDModule","note":""},
    {"id":"W-01","name":"Workspace speichern","module":"Workspace","status":"done","status_label":"Aktiv","tests":"TestWorkspacePersistence","note":".debussy.json"},
    {"id":"W-02","name":"Workspace laden","module":"Workspace","status":"done","status_label":"Aktiv","tests":"TestWorkspacePersistence","note":""},
    {"id":"W-03","name":"Dictionary","module":"Workspace","status":"done","status_label":"Aktiv","tests":"TestWorkspaceBasic","note":""},
    {"id":"X-01","name":"Goobi-XML-Export","module":"Export","status":"done","status_label":"Aktiv","tests":"TestGoobiExport (6)","note":"goobi-import Format"},
    {"id":"X-02","name":"Goobi Batch-Export","module":"Export","status":"done","status_label":"Aktiv","tests":"TestGoobiExport","note":""},
    {"id":"K-01","name":"Provider-Abstraktion","module":"KI","status":"done","status_label":"Aktiv","tests":"TestMockProvider","note":"GPUStack/Ollama/Mock"},
    {"id":"K-02","name":"System-Prompts","module":"KI","status":"done","status_label":"Aktiv","tests":"GUI","note":"6 Presets"},
    {"id":"K-03","name":"Modell-Auswahl","module":"KI","status":"done","status_label":"Aktiv","tests":"GUI","note":""},
    {"id":"P-01","name":"Markdown-Report","module":"Report","status":"done","status_label":"Aktiv","tests":"TestReport","note":""},
    {"id":"R-01","name":"Wikidata","module":"Enrich","status":"no","status_label":"Geplant","tests":"—","note":"SPARQL"},
    {"id":"R-02","name":"OCR/HTR","module":"Analyse","status":"no","status_label":"Geplant","tests":"—","note":""},
    {"id":"R-03","name":"Goobi Viewer API","module":"Export","status":"no","status_label":"Geplant","tests":"—","note":"REST"},
]

FEATURES = [
    {"name":"CSV-Import","s":"done"},{"name":"Strukturelle Analyse (7 Checks)","s":"done"},
    {"name":"NER Hybrid (SpaCy+LLM)","s":"done"},{"name":"EDTF-Normalisierung","s":"done"},
    {"name":"Problematische Begriffe","s":"done"},{"name":"GND-Lookup (live)","s":"done"},
    {"name":"Workspace-Persistenz","s":"done"},{"name":"Goobi-XML-Export","s":"done"},
    {"name":"Subject-Dictionary","s":"done"},{"name":"Entity-Editor","s":"done"},
    {"name":"Bild-Analyse","s":"beta"},{"name":"OCR/HTR","s":"planned"},
    {"name":"Wikidata","s":"planned"},{"name":"Goobi Viewer API","s":"planned"},
]

# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def _build_html():
    tpl = (_HTML_DIR / "dashboard.html").read_text(encoding="utf-8")
    return (tpl
        .replace("__PRESETS_JSON__", json.dumps(PRESETS, ensure_ascii=False))
        .replace("__TASKS_JSON__", json.dumps(TASKS_UI, ensure_ascii=False))
        .replace("__CATALOG_JSON__", json.dumps(CATALOG, ensure_ascii=False))
    )

# ---------------------------------------------------------------------------
# Core routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def dashboard(): return _build_html()

@app.get("/api/gpu/status")
async def gpu_status():
    c = _cfg()
    r = {"available": False, "models": [], "config": c.display_safe()}
    if c.is_gpustack_configured:
        try:
            p = GPUStackProvider(c.to_provider_config())
            r["available"] = p.is_available()
            if r["available"]: r["models"] = p.list_models()
        except Exception as e: r["error"] = str(e)
    return r

@app.post("/api/gpu/test")
async def gpu_test():
    prov = _prov()
    try:
        r = prov.complete([AIMessage.system("Test"), AIMessage.user("Sage 'OK'.")], max_tokens=10)
        return {"ok": True, "response": r.content, "model": r.model}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/analyze")
async def analyze(files: list[UploadFile] = File(...)):
    _state["datasets"] = {}
    datasets = []
    ws = _ws(); ws.source_files = []
    for u in files:
        content = await u.read()
        suffix = Path(u.filename).suffix or ".csv"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content); tp = Path(tmp.name)
        try:
            df, pr = ingest_csv(tp)
            pr.source_name = Path(u.filename).stem; pr.source_path = u.filename
            datasets.append((df, pr)); _state["datasets"][u.filename] = (df, pr)
            ws.source_files.append(u.filename)
        except Exception as e:
            return JSONResponse({"error": f"{u.filename}: {e}"}, 400)
        finally: tp.unlink(missing_ok=True)
    report = analyze_datasets(datasets); _state["report"] = report
    return _report_json(report, render_report(report))

@app.get("/api/dataset/{name}/columns")
async def dataset_columns(name: str):
    ds = _state["datasets"].get(name)
    if not ds: return JSONResponse({"error": f"'{name}' nicht geladen"}, 404)
    _, pr = ds
    return {"columns": [{"name":c.name,"fill_rate":c.fill_rate,"unique_count":c.unique_count,
                         "sample_values":c.sample_values[:3]} for c in pr.columns]}

@app.get("/api/dataset/{name}/records")
async def dataset_records(name: str):
    ds = _state["datasets"].get(name)
    if not ds: return JSONResponse({"error": "Nicht geladen"}, 404)
    df, pr = ds
    id_col = pr.id_column or df.columns[0]
    ids = df[id_col].dropna().astype(str).unique().tolist()
    return {"record_ids": ids[:200]}

# ---------------------------------------------------------------------------
# NER
# ---------------------------------------------------------------------------
@app.post("/api/ner")
async def api_ner(request: dict):
    dsn = request.get("dataset","")
    ds = _state["datasets"].get(dsn)
    if not ds: return JSONResponse({"error":"Datensatz nicht geladen"},400)
    df, profile = ds
    cols = request.get("columns", [])
    if not cols: cols = [c for c in df.columns if df[c].dtype == object]
    method = request.get("method", "llm")
    ss = min(request.get("sample_size", 10), 500)
    syp = request.get("system_prompt", "")
    mod = request.get("model", "")
    prov = _prov(mod)
    ws = _ws()

    result = ner_hybrid(
        df, cols, provider=prov if method != "spacy" else None,
        id_column=profile.id_column, sample_size=ss,
        model=mod or None, system_prompt=syp,
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
@app.post("/api/scan")
async def api_scan(request: dict):
    dsn = request.get("dataset","")
    ds = _state["datasets"].get(dsn)
    if not ds: return JSONResponse({"error":"Datensatz nicht geladen"},400)
    df, profile = ds
    ss = min(request.get("sample_size", 20), 500)
    syp = request.get("system_prompt", "")
    prov = _prov()
    issues, batch = scan_problematic_terms(
        df, prov, id_column=profile.id_column,
        sample_size=ss, system_prompt=syp)
    return {"task_name":"Scan","total":batch.total,"succeeded":batch.succeeded,
            "issues":issues[:200]}

# ---------------------------------------------------------------------------
# EDTF
# ---------------------------------------------------------------------------
@app.post("/api/edtf")
async def api_edtf(request: dict):
    dsn = request.get("dataset","")
    ds = _state["datasets"].get(dsn)
    if not ds: return JSONResponse({"error":"Datensatz nicht geladen"},400)
    df, profile = ds
    col = request.get("column","")
    if not col: return JSONResponse({"error":"Spalte wählen"},400)
    if col not in df.columns: return JSONResponse({"error":f"Spalte '{col}' nicht vorhanden"},400)
    ss = request.get("sample_size", 0)
    use_llm = request.get("use_llm", False)
    syp = request.get("system_prompt", "")
    ws = _ws()

    mask = df[col].replace("", pd.NA).notna()
    working = df[mask]
    if ss and ss > 0 and ss < len(working):
        working = working.sample(n=ss, random_state=42)

    items = [{"record_id": str(row.get(profile.id_column, "")) if profile.id_column else "",
              "text": str(row[col]).strip()}
             for _, row in working.iterrows() if str(row[col]).strip()]

    prov = _prov() if use_llm else None
    results, batch = normalize_dates(items, provider=prov, system_prompt=syp)

    # Save to workspace
    ws.add_dates([{"original":r.original,"edtf":r.edtf,"confidence":r.confidence,
                   "method":r.method,"record_id":r.record_id,"column":col}
                  for r in results], replace=True)

    converted = len([r for r in results if r.edtf])
    undated = len([r for r in results if not r.edtf and r.note == "undatiert"])
    failed = len(results) - converted - undated

    return {
        "task_name": "EDTF", "total": len(results),
        "converted": converted, "failed": failed, "undated": undated,
        "results": [{"record_id":r.record_id,"original":r.original,"edtf":r.edtf,
                     "confidence":round(r.confidence,3),"method":r.method,"note":r.note}
                    for r in results],
    }

# ---------------------------------------------------------------------------
# GND search
# ---------------------------------------------------------------------------
@app.get("/api/gnd/search")
async def gnd_search_api(q: str = "", type: str = "", size: int = 5):
    if not q: return {"results": []}
    results = gnd_search(q, entity_type=type, size=size)
    return {"results": [r.to_dict() for r in results]}

@app.post("/api/gnd/batch")
async def gnd_batch_api(request: dict):
    """Run GND lookup for workspace entities."""
    ws = _ws()
    unique = ws.unique_entities()
    if not unique: return JSONResponse({"error":"Erst NER ausführen"},400)
    limit = min(request.get("limit", 50), 200)
    terms = [{"text":e.text, "type":e.entity_type, "record_id":e.record_id}
             for e in unique[:limit]]
    results = gnd_batch_search(terms, delay=0.15)
    matched = 0
    for gr in results:
        if gr.get("top_match"):
            tm = gr["top_match"]
            for i, e in enumerate(ws.entities):
                if e.text == gr["text"] and e.entity_type == gr["type"]:
                    ws.update_entity(i, {"gnd_id":tm["gnd_id"],"gnd_preferred":tm["preferred_name"]})
            ws.add_to_dictionary([{
                "term":gr["text"],"gnd_id":tm["gnd_id"],"gnd_preferred":tm["preferred_name"],
                "category":gr["type"],"source":"gnd-api"}])
            matched += 1
    return {"total":len(terms),"matched":matched,"results":results,
            "dictionary_size":len(ws.dictionary)}

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@app.post("/api/export/goobi-preview")
async def export_goobi_preview(request: dict):
    dsn = request.get("dataset","")
    ds = _state["datasets"].get(dsn)
    if not ds: return JSONResponse({"error":"Datensatz nicht geladen"},400)
    df, profile = ds
    ws = _ws()
    rid = request.get("record_id","")
    if rid:
        df_filtered = df[df[profile.id_column or df.columns[0]].astype(str) == rid]
        if df_filtered.empty: return JSONResponse({"error":f"Record '{rid}' nicht gefunden"},400)
    else:
        df_filtered = df.head(1)
    fmap = ws.field_mapping or {}
    results = export_goobi_xml(df_filtered, ws,
                               record_id_col=profile.id_column or "record_id",
                               field_map={k:tuple(v) if isinstance(v,(list,tuple)) else v for k,v in fmap.items()})
    if results:
        return {"xml": results[0][1], "record_id": results[0][0]}
    return {"xml": "<!-- Kein Record -->", "record_id": ""}

@app.post("/api/export/goobi-batch")
async def export_goobi_batch_api(request: dict):
    dsn = request.get("dataset","")
    ds = _state["datasets"].get(dsn)
    if not ds: return JSONResponse({"error":"Datensatz nicht geladen"},400)
    df, profile = ds
    ws = _ws()
    xml = export_goobi_batch(df, ws, record_id_col=profile.id_column or "record_id")
    return {"xml": xml, "record_count": len(df)}

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
@app.get("/api/workspace")
async def workspace_get(): return _ws().to_summary()

@app.get("/api/workspace/entities")
async def workspace_entities():
    ws = _ws()
    return {"entities":[
        {"idx":i,"text":e.text,"type":e.entity_type,"confidence":e.confidence,
         "source":e.source,"record_id":e.record_id,"gnd_id":e.gnd_id,
         "gnd_preferred":e.gnd_preferred,"status":e.status,"editor_note":e.editor_note}
        for i,e in enumerate(ws.entities)
    ],"status_counts":ws.entities_by_status()}

@app.post("/api/workspace/entity/{idx}")
async def workspace_entity_update(idx: int, updates: dict):
    if _ws().update_entity(idx, updates): return {"ok":True}
    return JSONResponse({"error":"Index ungültig"},400)

@app.post("/api/workspace/entity/batch")
async def workspace_entity_batch(request: dict):
    indices = request.get("indices",[]); updates = request.get("updates",{})
    count = sum(1 for i in indices if _ws().update_entity(i, updates))
    return {"updated":count}

@app.get("/api/workspace/dictionary")
async def workspace_dictionary():
    ws = _ws()
    return {"entries":[
        {"idx":i,"term":e.term,"normalized":e.normalized,"gnd_id":e.gnd_id,
         "gnd_preferred":e.gnd_preferred,"category":e.category,"status":e.status}
        for i,e in enumerate(ws.dictionary)
    ]}

@app.post("/api/workspace/save")
async def workspace_save(request: dict):
    name = request.get("name","project")
    path = Path(tempfile.gettempdir()) / f"{name}.debussy.json"
    _ws().name = name; _ws().save(path)
    return {"path":str(path),"summary":_ws().to_summary()}

@app.post("/api/workspace/load")
async def workspace_load(file: UploadFile = File(...)):
    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
        tmp.write(content); tp = Path(tmp.name)
    try:
        _state["workspace"] = Workspace.load(tp)
        return _ws().to_summary()
    finally: tp.unlink(missing_ok=True)

# ---------------------------------------------------------------------------
# KI-Beschreibungen
# ---------------------------------------------------------------------------
@app.post("/api/ai/describe-columns")
async def ai_describe_columns():
    if not _state["datasets"]: return JSONResponse({"error":"Keine Daten"},400)
    prov = _prov()
    all_ds = []
    for name, (df, profile) in _state["datasets"].items():
        cols = []
        for cp in profile.columns:
            vals = df[cp.name].replace("",pd.NA).dropna().astype(str).unique()[:5].tolist()
            ctx = f"Spalte '{cp.name}', {cp.fill_rate:.0%} gefüllt, {cp.unique_count} unique. Beispiele: {', '.join(vals)}"
            try:
                r = prov.complete([AIMessage.system(SYSTEM_METADATA_EXPERT_DE),
                    AIMessage.user(f"Beschreibe kurz:\n{ctx}\nJSON: {{\"description\":\"...\"}}")],
                    max_tokens=200)
                p = _try_parse_json(r.content)
                desc = p.get("description",r.content) if p else r.content
            except Exception as e: desc = f"(Fehler: {e})"
            cols.append({"name":cp.name,"fill_rate":cp.fill_rate,"unique_count":cp.unique_count,
                        "description":f"{cp.fill_rate:.0%}, {cp.unique_count} Werte","ai_description":desc})
        all_ds.append({"name":profile.source_name,"columns":cols})
    return {"datasets":all_ds}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _report_json(report, md):
    return {
        "summary":report.summary,
        "datasets":[{"source_name":p.source_name,"source_path":p.source_path,"row_count":p.row_count,
            "column_count":p.column_count,"id_column":p.id_column,"encoding_detected":p.encoding_detected,
            "has_bom":p.has_bom,"line_ending":p.line_ending,
            "columns":[{"name":c.name,"fill_rate":c.fill_rate,"unique_count":c.unique_count,
                "sample_values":c.sample_values} for c in p.columns]} for p in report.datasets],
        "findings":[{"category":f.category.value,"severity":f.severity.value,"message":f.message,
            "column":f.column,"record_ids":f.record_ids[:10],"suggestion":f.suggestion} for f in report.findings],
        "markdown":md}

if __name__ == "__main__":
    print("=" * 50)
    print("  Debussy v0.5  —  http://localhost:8765")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8765)
