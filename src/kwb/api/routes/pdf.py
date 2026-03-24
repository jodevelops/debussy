"""
PDF routes — upload, text extraction (OCR), and NER.

  POST /api/pdf/upload  — upload PDF files, returns page metadata
  GET  /api/pdf/list    — list uploaded PDFs with extraction status
  POST /api/pdf/extract — OCR text extraction via vision LLM → structured JSON
  POST /api/pdf/ner     — NER on extracted text → structured JSON

Structured JSON output format for /api/pdf/extract:
{
  "document": "filename.pdf",
  "doc_id": "abc12345",
  "pages": [
    {"page": 1, "text": "...", "confidence": "high"},
    ...
  ],
  "total_pages": 5,
  "extracted_pages": 3
}

Structured JSON output format for /api/pdf/ner:
{
  "document": "filename.pdf",
  "doc_id": "abc12345",
  "entities": [
    {
      "text": "Max Mustermann",
      "type": "PER",
      "confidence": 0.92,
      "reasoning": "Personenname erkannt",
      "source": "page_1"
    }
  ],
  "entity_count": 12,
  "entity_types": {"PER": 3, "LOC": 5, "ORG": 4}
}

Router prefix: /api
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

try:
    from fastapi import APIRouter, File, UploadFile
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError("pip install fastapi uvicorn python-multipart")

from kwb.api.deps import MAX_FILE_BYTES, get_provider

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory PDF store — metadata + extracted content
# (mirrors the image store pattern; resets on server restart)
# ---------------------------------------------------------------------------
_pdf_store: dict[str, dict] = {}

_PDF_DIR = Path(tempfile.gettempdir()) / "debussy_pdfs"
_PDF_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@router.post("/api/pdf/upload")
async def pdf_upload(files: list[UploadFile] = File(...)):
    """Upload PDF files and return per-document page metadata."""
    results = []
    for u in files:
        fname = u.filename or "document.pdf"
        if not fname.lower().endswith(".pdf"):
            return JSONResponse({"error": f"'{fname}': Nur PDF-Dateien erlaubt"}, 400)

        content = await u.read()
        if len(content) > MAX_FILE_BYTES:
            return JSONResponse(
                {"error": f"'{fname}': Max {MAX_FILE_BYTES // (1024 * 1024)} MB"},
                400,
            )

        doc_id = str(uuid.uuid4())[:8]
        disk_path = _PDF_DIR / f"{doc_id}.pdf"
        disk_path.write_bytes(content)

        pages_raw = []
        page_meta = []
        error_note = None

        try:
            from kwb.ingest.pdf_loader import pdf_to_images
            pages_raw = pdf_to_images(disk_path, max_pages=200, dpi=150)
            page_meta = [
                {
                    "page": i + 1,
                    "filename": getattr(p, "filename", f"page_{i + 1}.png"),
                    "width": getattr(p, "width", None),
                    "height": getattr(p, "height", None),
                    "size_bytes": getattr(p, "file_size_bytes", 0),
                }
                for i, p in enumerate(pages_raw)
            ]
        except Exception as exc:
            error_note = str(exc)
            page_meta = [{"page": 1, "error": error_note}]

        page_count = len(pages_raw) if pages_raw else (1 if error_note else 0)

        _pdf_store[doc_id] = {
            "id": doc_id,
            "filename": fname,
            "path": str(disk_path),
            "page_count": page_count,
            "page_meta": page_meta,
            "_pages_raw": pages_raw,
            "extracted": {},   # {page_num (int): text (str)}
            "entities": [],
        }

        results.append({
            "id": doc_id,
            "filename": fname,
            "page_count": page_count,
            "size_bytes": len(content),
            "pages": page_meta[:10],
            **({"error": error_note} if error_note else {}),
        })

    return {"uploaded": results, "total": len(results)}


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get("/api/pdf/list")
async def pdf_list():
    """Return metadata for all uploaded PDF documents."""
    return {
        "documents": [
            {
                "id": d["id"],
                "filename": d["filename"],
                "page_count": d["page_count"],
                "extracted_pages": len(d["extracted"]),
                "entities_count": len(d["entities"]),
            }
            for d in _pdf_store.values()
        ]
    }


# ---------------------------------------------------------------------------
# Text Extraction (OCR via vision LLM)
# ---------------------------------------------------------------------------

@router.post("/api/pdf/extract")
async def pdf_extract(request: dict):
    """
    Extract text from PDF pages using a vision LLM (OCR).

    Returns structured JSON with one entry per extracted page.
    """
    doc_id = (request.get("doc_id") or "").strip()
    model = (request.get("model") or "").strip()
    raw_max = request.get("max_pages")
    try:
        max_pages = int(raw_max) if raw_max is not None else 20
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": f"Ungültiger Wert für max_pages: {raw_max!r}"}, 422
        )
    if max_pages < 1:
        return JSONResponse(
            {"error": "max_pages muss mindestens 1 sein."}, 422
        )
    max_pages = min(max_pages, 200)

    doc = _pdf_store.get(doc_id)
    if not doc:
        return JSONResponse(
            {"error": f"Dokument '{doc_id}' nicht gefunden. Bitte erst hochladen (/api/pdf/upload)."},
            404,
        )

    pages_raw = doc.get("_pages_raw") or []
    if not pages_raw:
        # Try reloading from disk
        try:
            from kwb.ingest.pdf_loader import pdf_to_images
            pages_raw = pdf_to_images(Path(doc["path"]), max_pages=max_pages, dpi=150)
            doc["_pages_raw"] = pages_raw
        except Exception as exc:
            return JSONResponse({"error": f"PDF-Ladevorgang fehlgeschlagen: {exc}"}, 500)

    if not pages_raw:
        return JSONResponse(
            {
                "error": (
                    "Keine Seiten verfügbar. Bitte pdf2image oder pypdf installieren: "
                    "pip install pdf2image pypdf"
                )
            },
            400,
        )

    from kwb.ai.provider import AIMessage
    prov = get_provider(model)

    # Clear prior extracted pages so a re-run with fewer max_pages
    # does not leave stale entries that NER would process.
    doc["extracted"] = {}

    extracted_pages = []
    for i, page in enumerate(pages_raw[:max_pages]):
        page_num = i + 1
        b64 = getattr(page, "base64_data", "") or ""
        if not b64:
            continue
        try:
            messages = [
                AIMessage.system(
                    "Du bist ein OCR-Experte für historische und archivalische Dokumente. "
                    "Transkribiere allen sichtbaren Text exakt wie er erscheint, "
                    "einschließlich Absätze, Zeilenumbrüche und Sonderzeichen. "
                    "Antworte ausschließlich mit dem transkribierten Text, ohne Kommentare."
                ),
                AIMessage.user_with_image(
                    "Bitte transkribiere den vollständigen Text dieser Seite.",
                    b64,
                    mime_type=getattr(page, "mime_type", "image/png") or "image/png",
                ),
            ]
            resp = prov.complete(messages, model=model or None, max_tokens=2000)
            text = resp.content if resp else ""
            confidence = "high" if text and not text.startswith("[") else "low"
        except Exception as exc:
            text = f"[Extraktionsfehler Seite {page_num}: {exc}]"
            confidence = "error"

        doc["extracted"][page_num] = text
        extracted_pages.append({
            "page": page_num,
            "text": text,
            "confidence": confidence,
        })

    return {
        "document": doc["filename"],
        "doc_id": doc_id,
        "pages": extracted_pages,
        "total_pages": doc["page_count"],
        "extracted_pages": len(extracted_pages),
    }


# ---------------------------------------------------------------------------
# NER on extracted text → structured JSON
# ---------------------------------------------------------------------------

@router.post("/api/pdf/ner")
async def pdf_ner(request: dict):
    """
    Run Named Entity Recognition on extracted PDF text.

    Returns structured JSON with deduplicated entities and type counts.
    """
    doc_id = (request.get("doc_id") or "").strip()
    model = (request.get("model") or "").strip()
    entity_types = request.get("entity_types") or []

    doc = _pdf_store.get(doc_id)
    if not doc:
        return JSONResponse({"error": f"Dokument '{doc_id}' nicht gefunden"}, 404)

    extracted = doc.get("extracted") or {}
    if not extracted:
        return JSONResponse(
            {"error": "Kein extrahierter Text vorhanden. Bitte erst /api/pdf/extract aufrufen."},
            400,
        )

    import pandas as pd
    from kwb.analyze.ner import ner_hybrid

    prov = get_provider(model)
    all_entities: list[dict] = []
    page_errors: list[dict] = []

    for page_num in sorted(extracted.keys()):
        text = extracted[page_num]
        if not text or str(text).startswith("["):
            continue
        try:
            df = pd.DataFrame({"text": [text]})
            result = ner_hybrid(
                df,
                ["text"],
                provider=prov,
                id_column=None,
                sample_size=None,
                model=model or None,
                use_spacy=False,
                use_llm=True,
                entity_types=entity_types or None,
            )
            for e in result.to_dict_list(deduplicated=True):
                e["source"] = f"page_{page_num}"
                all_entities.append(e)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "NER failed for page %s of %s: %s", page_num, doc_id, exc
            )
            page_errors.append({"page": page_num, "error": str(exc)})

    # Deduplicate across pages, keeping highest confidence
    seen: dict[str, dict] = {}
    for e in all_entities:
        key = f"{str(e.get('text', '')).strip().lower()}||{e.get('type', 'CON')}"
        if key not in seen or float(e.get("confidence", 0)) > float(seen[key].get("confidence", 0)):
            seen[key] = e
    deduped = list(seen.values())

    type_counts: dict[str, int] = {}
    for e in deduped:
        t = str(e.get("type", "CON"))
        type_counts[t] = type_counts.get(t, 0) + 1

    doc["entities"] = deduped

    response = {
        "document": doc["filename"],
        "doc_id": doc_id,
        "entities": deduped,
        "entity_count": len(deduped),
        "entity_types": type_counts,
    }
    if page_errors:
        response["page_errors"] = page_errors
    return response
