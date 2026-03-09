"""
Debussy v0.6 — KI-gestützte Kuratierungswerkbank.

PYTHONPATH=src python -m kwb.api.app → http://localhost:8765

Architecture:
  app.py          — FastAPI app, router registration, HTML template
  routes/analyze  — /api/analyze, /api/dataset/*, /api/ner, /api/scan, /api/edtf
  routes/enrich   — /api/gnd/*
  routes/export   — /api/export/*
  routes/workspace — /api/workspace/*
  routes/ai       — /api/gpu/*, /api/ai/*, /api/images/*
  deps.py         — shared state, config, provider factory
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    import uvicorn
except ImportError:
    print("pip install fastapi uvicorn python-multipart")
    sys.exit(1)

from kwb.analyze.ner import SYSTEM_NER
from kwb.enrich.edtf import SYSTEM_EDTF
from kwb.ai.prompts import (
    SYSTEM_METADATA_EXPERT_DE, SYSTEM_METADATA_EXPERT_EN,
    SYSTEM_VISION_EXPERT_DE,
    prompt_image_description,
    prompt_person_face_visibility,
    prompt_ocr_transcription_quality,
    prompt_entity_extraction_normdata,
)

# Route modules
from kwb.api.routes.analyze import router as analyze_router
from kwb.api.routes.enrich import router as enrich_router
from kwb.api.routes.export import router as export_router
from kwb.api.routes.workspace import router as workspace_router
from kwb.api.routes.ai import router as ai_router
from kwb.api.routes.dictionary import router as dictionary_router
from kwb.api.routes.mds_tasks import router as mds_tasks_router
from kwb.api.routes.auth import router as auth_router

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Debussy",
    version="0.6.0",
    description="KI-gestützte Kuratierungswerkbank für GLAM-Sammlungen",
)

app.include_router(analyze_router)
app.include_router(enrich_router)
app.include_router(export_router)
app.include_router(workspace_router)
app.include_router(ai_router)
app.include_router(dictionary_router)
app.include_router(mds_tasks_router)
app.include_router(auth_router)

# ---------------------------------------------------------------------------
# UI data injected into the dashboard HTML template
# ---------------------------------------------------------------------------
_HTML_DIR = Path(__file__).parent

PRESETS = {
    "meta_de": SYSTEM_METADATA_EXPERT_DE,
    "meta_en": SYSTEM_METADATA_EXPERT_EN,
    "vision_de": SYSTEM_VISION_EXPERT_DE,
    "img_desc_de": prompt_image_description()[1].content,
    "img_faces_de": prompt_person_face_visibility()[1].content,
    "ocr_de": prompt_ocr_transcription_quality()[1].content,
    "entity_norm_de": prompt_entity_extraction_normdata("Beispiel")[1].content,
    "ner_de": SYSTEM_NER,
    "edtf_de": SYSTEM_EDTF,
    "scan_de": (
        "Du bist ein Experte fuer Metadatenqualitaet. "
        "Identifiziere veraltete, koloniale oder problematische Begriffe. "
        "Antworte als JSON."
    ),
    "custom": "",
}

TASKS_UI = {
    "ner": {
        "name": "Named Entity Recognition", "type": "NER",
        "description": "Erkennt Personen, Orte, Organisationen etc. (SpaCy+LLM)",
    },
    "scan": {
        "name": "Problematische Begriffe", "type": "Scan",
        "description": "Durchsucht Datenset nach veralteten/kolonialen Begriffen",
    },
    "edtf": {
        "name": "EDTF-Normalisierung", "type": "EDTF",
        "description": "Datumsangaben → LOC Extended Date/Time Format",
    },
    "gnd": {
        "name": "GND-Lookup", "type": "GND",
        "description": "Echte GND-IDs via lobid.org API (kein KI-Raten)",
    },
    "classify": {
        "name": "Schlagwort-Klassifikation", "type": "KI",
        "description": "Klassifiziert Subjects in NER-Kategorien",
    },
    "describe": {
        "name": "Spalten-Beschreibungen", "type": "KI",
        "description": "KI-generierte Inhaltsbeschreibungen",
    },
    "images": {
        "name": "Bild-Analyse", "type": "Vision",
        "description": "KI-gestützte Bildbeschreibung (Vision-Modell erforderlich)",
    },
    "export": {
        "name": "Goobi-XML-Export", "type": "Export",
        "description": "Export im goobi-import Format mit kuratierten Entities",
    },
}

# Function catalogue — single source of truth, rendered in dashboard
CATALOG = [
    # Ingest
    {"id": "I-01", "name": "CSV-Import",         "module": "Ingest",    "status": "done",    "note": "Encoding-Erkennung"},
    {"id": "I-02", "name": "Datei-Selektion",     "module": "Ingest",    "status": "done",    "note": "Checkbox"},
    {"id": "I-03", "name": "Bild-Upload (API)",   "module": "Ingest",    "status": "done",    "note": "/api/images/upload"},
    {"id": "I-03a","name": "Bild-Analyse (GUI)",  "module": "Ingest",    "status": "partial", "note": "API vorhanden, Tab in Arbeit"},
    # Analysis
    {"id": "A-01", "name": "Fehlende Werte",      "module": "Analyse",   "status": "done",    "note": ""},
    {"id": "A-02", "name": "Duplikate",           "module": "Analyse",   "status": "done",    "note": ""},
    {"id": "A-03", "name": "Encoding",            "module": "Analyse",   "status": "done",    "note": ""},
    {"id": "A-04", "name": "Format-Inkonsistenzen","module": "Analyse",  "status": "done",    "note": ""},
    {"id": "A-05", "name": "Term-Varianten",      "module": "Analyse",   "status": "done",    "note": ""},
    {"id": "A-06", "name": "Cross-File-Linkage",  "module": "Analyse",   "status": "done",    "note": ""},
    {"id": "A-07", "name": "GND-Abdeckung",       "module": "Analyse",   "status": "done",    "note": ""},
    # NER
    {"id": "N-01", "name": "NER (LLM)",           "module": "NER",       "status": "done",    "note": "10 Entity-Typen"},
    {"id": "N-02", "name": "NER (SpaCy)",         "module": "NER",       "status": "done",    "note": "Optional"},
    {"id": "N-03", "name": "NER Hybrid",          "module": "NER",       "status": "done",    "note": "SpaCy+LLM, dedupliziert, _merge_entity_lists"},
    {"id": "N-04", "name": "Problematische Begriffe","module": "NER",    "status": "done",    "note": "LLM-basiert (NER-Tab)"},
    {"id": "N-06", "name": "Begriffe-Wörterbuch",   "module": "Begriffe","status": "done",    "note": "Dictionary-Scan, eigener Tab, CSV/JSON/TXT Upload"},
    {"id": "N-05", "name": "Entity-Editor",       "module": "NER",       "status": "done",    "note": "Accept/Reject/Status-Filter"},
    # EDTF
    {"id": "E-01", "name": "EDTF Regeln",         "module": "EDTF",      "status": "done",    "note": "normalize/edtf.py — Umlaut-Monate, Jahreszeiten, ISO"},
    {"id": "E-02", "name": "EDTF LLM-Fallback",   "module": "EDTF",      "status": "done",    "note": "normalize_edtf_hybrid"},
    {"id": "E-03", "name": "EDTF in GUI",         "module": "EDTF",      "status": "done",    "note": "Modell-Auswahl verdrahtet"},
    # Enrichment
    {"id": "G-01", "name": "GND-Lookup (live)",   "module": "Enrich",    "status": "done",    "note": "lobid.org API"},
    {"id": "G-02", "name": "GND Batch",           "module": "Enrich",    "status": "done",    "note": ""},
    {"id": "G-03", "name": "GND Ergebnis-Tabelle","module": "Enrich",    "status": "done",    "note": "gndtbl in GUI"},
    # Workspace
    {"id": "W-01", "name": "Workspace speichern", "module": "Workspace", "status": "done",    "note": ".debussy.json (inkl. Bildanalyse-Ergebnisse)"},
    {"id": "W-02", "name": "Workspace laden",     "module": "Workspace", "status": "done",    "note": ""},
    {"id": "W-03", "name": "Dictionary",          "module": "Workspace", "status": "done",    "note": ""},
    {"id": "W-04", "name": "Field Mapping GUI",   "module": "Workspace", "status": "done",    "note": "CSV → Minimaldatensatz 1.1 / Goobi-Typ"},
    {"id": "W-05", "name": "ID-Spalten-Auswahl", "module": "Workspace", "status": "done",    "note": "Manuelle Auswahl nach CSV-Upload, Unique-Prüfung"},
    # Export
    {"id": "X-01", "name": "Goobi-XML-Export",    "module": "Export",    "status": "done",    "note": "goobi-import Format"},
    {"id": "X-02", "name": "Goobi Batch-Export",  "module": "Export",    "status": "done",    "note": ""},
    {"id": "X-03", "name": "Field-Mapping",       "module": "Export",    "status": "done",    "note": ""},
    # KI Infrastructure
    {"id": "K-01", "name": "GPUStack-Provider",   "module": "KI",        "status": "done",    "note": ""},
    {"id": "K-02", "name": "Ollama-Provider",     "module": "KI",        "status": "done",    "note": "Local dev fallback"},
    {"id": "K-03", "name": "Mock-Provider",       "module": "KI",        "status": "done",    "note": "Tests + kein GPU"},
    {"id": "K-04", "name": "System-Prompts",      "module": "KI",        "status": "done",    "note": "6 Presets"},
    {"id": "K-05", "name": "Modell-Auswahl",      "module": "KI",        "status": "done",    "note": "Alle Endpoints"},
    {"id": "K-06", "name": "Bild-Analyse (API)",  "module": "KI",        "status": "done",    "note": "/api/images/analyze, Ergebnisse in Workspace persistiert"},
    # Report
    {"id": "P-01", "name": "Markdown-Report",     "module": "Report",    "status": "done",    "note": ""},
    # Geplant
    {"id": "R-01", "name": "Wikidata",            "module": "Enrich",    "status": "planned", "note": "SPARQL"},
    {"id": "R-02", "name": "OCR/HTR",             "module": "Analyse",   "status": "planned", "note": ""},
    {"id": "R-03", "name": "Goobi Viewer API",    "module": "Export",    "status": "done",    "note": "REST Push via /api/goobi/*"},
    {"id": "R-04", "name": "METS/MODS Export",    "module": "Export",    "status": "planned", "note": ""},
    {"id": "R-05", "name": "GeoNames Lookup",     "module": "Enrich",    "status": "planned", "note": ""},
    {"id": "R-06", "name": "XML/PDF Ingest",      "module": "Ingest",    "status": "planned", "note": ""},
]


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------
def _build_html() -> str:
    _parts = _HTML_DIR / "parts"
    css = (_parts / "dashboard.css").read_text(encoding="utf-8")
    js = (_parts / "dashboard.js").read_text(encoding="utf-8")
    tpl = (_HTML_DIR / "dashboard.html").read_text(encoding="utf-8")
    version = app.version
    return (
        tpl
        .replace("<!-- CSS_PLACEHOLDER -->", f"<style>{css}</style>")
        .replace("<!-- JS_PLACEHOLDER -->", f"<script>{js}</script>")
        .replace("__PRESETS_JSON__", json.dumps(PRESETS, ensure_ascii=False))
        .replace("__TASKS_JSON__", json.dumps(TASKS_UI, ensure_ascii=False))
        .replace("__CATALOG_JSON__", json.dumps(CATALOG, ensure_ascii=False))
        .replace("__VERSION__", version)
    )


@app.get("/", response_class=HTMLResponse)
async def index():
    return _build_html()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    host = os.environ.get("KWB_HOST", "127.0.0.1")
    port = int(os.environ.get("KWB_PORT", "8765"))
    if host != "127.0.0.1":
        print(f"⚠️  Binding to {host} — no auth configured!")
    print("=" * 50)
    print(f"  Debussy v0.6.0  —  http://{host}:{port}")
    print("=" * 50)
    uvicorn.run(app, host=host, port=port)
