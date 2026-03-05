"""
AI / infrastructure routes:
  /api/gpu/status   — GPUStack connectivity check
  /api/gpu/test     — single LLM call test
  /api/ai/describe-columns — LLM-generated column descriptions
  /api/images/upload — upload images for visual analysis
  /api/images/analyze — run LLM vision analysis on uploaded images

Router prefix: /api
"""
from __future__ import annotations

import base64
import tempfile as _tempfile
from pathlib import Path

try:
    from fastapi import APIRouter, File, UploadFile
    from fastapi.responses import JSONResponse, Response
except ImportError:
    raise ImportError("pip install fastapi uvicorn python-multipart")

from kwb.api.deps import (
    ALLOWED_IMAGE_EXT, MAX_FILE_BYTES, MAX_IMAGE_FILES,
    get_config, get_datasets, get_provider, get_workspace,
)
from kwb.ai.provider import AIMessage
from kwb.ai.batch import process_batch
from kwb.ai.prompts import SYSTEM_VISION_EXPERT_DE, SYSTEM_METADATA_EXPERT_DE
from kwb.core.workspace import ImageAnalysisResult

router = APIRouter()

# ---------------------------------------------------------------------------
# GPU / Provider status
# ---------------------------------------------------------------------------

@router.get("/api/gpu/status")
async def gpu_status():
    c = get_config()
    if not c.is_gpustack_configured:
        return {"status": "mock", "configured": False,
                "message": "GPUStack nicht konfiguriert — Mock-Modus aktiv"}
    try:
        from kwb.ai.gpustack import GPUStackProvider
        prov = GPUStackProvider(c.to_provider_config())
        available = prov.is_available()
        models = prov.list_models() if available else []
        return {"status": "ok" if available else "error",
                "configured": True, "available": available, "models": models}
    except Exception as e:
        return {"status": "error", "configured": True, "message": str(e)}


@router.post("/api/gpu/test")
async def gpu_test(request: dict | None = None):
    request = request or {}
    mod = request.get("model", "")
    syp = request.get("system_prompt", "Antworte in einem Satz.")
    prov = get_provider(mod)
    try:
        resp = prov.complete(
            [AIMessage.system(syp), AIMessage.user("Sag: Test erfolgreich.")],
            model=mod or None, max_tokens=60,
        )
        return {"status": "ok", "model": resp.model, "response": resp.content[:200]}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, 500)


# ---------------------------------------------------------------------------
# AI column descriptions
# ---------------------------------------------------------------------------

@router.post("/api/ai/describe-columns")
async def ai_describe_columns(request: dict | None = None):
    request = request or {}
    dsn = request.get("dataset", "")
    datasets = get_datasets()
    if dsn:
        ds = datasets.get(dsn)
    elif datasets:
        dsn, ds = next(iter(datasets.items()))
    else:
        ds = None
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds
    mod = request.get("model", "")
    prov = get_provider(mod)
    syp = request.get("system_prompt", SYSTEM_METADATA_EXPERT_DE)

    items = [{"column": c.name, "sample": str(c.sample_values[:5])} for c in profile.columns]

    def _prompt(item):
        return [
            AIMessage.system(syp),
            AIMessage.user(
                f"Beschreibe die Spalte '{item['column']}' kurz auf Deutsch.\n"
                f"Beispielwerte: {item['sample']}\n"
                f'Antworte als JSON: {{"column": "{item["column"]}", "description": "...", "data_type": "..."}}'
            ),
        ]

    batch = process_batch(prov, items, _prompt, model=mod or None)
    descriptions = {}
    for i, br in enumerate(batch.results):
        col = items[i]["column"]
        if br.parsed:
            descriptions[col] = br.parsed
        else:
            descriptions[col] = {"column": col, "description": br.raw or "", "data_type": "unbekannt"}

    col_list = []
    for c in profile.columns:
        desc = descriptions.get(c.name, {})
        col_list.append({
            "name": c.name,
            "ai_description": desc.get("description", ""),
            "data_type": desc.get("data_type", ""),
        })

    return {
        "datasets": [{
            "name": dsn,
            "columns": col_list,
        }],
        "descriptions": descriptions,
        "model": mod or "default",
    }


# ---------------------------------------------------------------------------
# Image analysis
# ---------------------------------------------------------------------------
# Image store — metadata in-memory, raw bytes on disk so they survive reloads
# ---------------------------------------------------------------------------

# Image storage directory — configurable via KWB_IMAGE_DIR env var.
# Falls back to system temp dir if not set.
import os as _os
_IMAGE_DIR = Path(_os.environ.get(
    "KWB_IMAGE_DIR",
    str(Path(_tempfile.gettempdir()) / "debussy_uploads"),
))
_IMAGE_DIR.mkdir(exist_ok=True)

# In-memory metadata index (rebuilt from disk on demand, see _sync_index)
_uploaded_images: dict[str, dict] = {}


def _sync_index() -> None:
    """Re-populate the metadata index from files on disk, restoring workspace results."""
    ext_to_mime = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".tif": "image/tiff",
        ".tiff": "image/tiff", ".webp": "image/webp",
    }
    # Restore analysis results from workspace if available
    ws = get_workspace()
    ws_results = {r.image_id: r for r in ws.image_analyses}

    for p in sorted(_IMAGE_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in ext_to_mime:
            img_id = p.stem
            if img_id not in _uploaded_images:
                ws_result = ws_results.get(img_id)
                _uploaded_images[img_id] = {
                    "id": img_id,
                    "filename": ws_result.filename if ws_result else p.name,
                    "media_type": ext_to_mime[p.suffix.lower()],
                    "size_bytes": p.stat().st_size,
                    "path": str(p),
                    "analyzed": ws_result.analyzed if ws_result else False,
                    "result": ws_result.result if ws_result else None,
                }


_sync_index()


@router.post("/api/images/upload")
async def images_upload(files: list[UploadFile] = File(...)):
    """
    Upload image files for visual analysis.

    Accepted formats: JPEG, PNG, TIFF, WebP.
    Returns a list of image handles (id + filename + preview dimensions).
    """
    if len(files) > MAX_IMAGE_FILES:
        return JSONResponse({"error": f"Max {MAX_IMAGE_FILES} Bilder"}, 400)

    accepted = []
    for u in files:
        suffix = Path(u.filename or "").suffix.lower()
        if suffix not in ALLOWED_IMAGE_EXT:
            return JSONResponse({
                "error": f"'{u.filename}': Nur {', '.join(ALLOWED_IMAGE_EXT)} erlaubt"
            }, 400)
        content = await u.read()
        if len(content) > MAX_FILE_BYTES:
            return JSONResponse({"error": f"'{u.filename}': Max 50 MB"}, 400)

        # Detect media type
        media_type = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".tif": "image/tiff",
            ".tiff": "image/tiff", ".webp": "image/webp",
        }.get(suffix, "image/jpeg")

        img_id = f"img_{len(_uploaded_images) + 1:04d}_{Path(u.filename).stem}"
        img_path = _IMAGE_DIR / f"{img_id}{suffix}"
        img_path.write_bytes(content)
        _uploaded_images[img_id] = {
            "id": img_id,
            "filename": u.filename,
            "media_type": media_type,
            "size_bytes": len(content),
            "path": str(img_path),
            "analyzed": False,
            "result": None,
        }
        accepted.append({
            "id": img_id,
            "filename": u.filename,
            "size_bytes": len(content),
            "media_type": media_type,
        })

    return {"uploaded": len(accepted), "images": accepted}


@router.get("/api/images/{img_id}/data")
async def image_data(img_id: str):
    """Serve raw image bytes (original format, may not be browser-renderable for TIFF)."""
    img = _uploaded_images.get(img_id)
    if not img:
        return JSONResponse({"error": "Nicht gefunden"}, 404)
    img_path = Path(img["path"])
    if not img_path.exists():
        return JSONResponse({"error": "Datei nicht gefunden"}, 404)
    return Response(content=img_path.read_bytes(), media_type=img["media_type"])


def _extract_tiff_jpeg_thumbnail(data: bytes) -> bytes | None:
    """
    Extract embedded JPEG thumbnail from TIFF IFD tags 513/514 (JPEGInterchangeFormat).

    Many archival TIFFs contain a full embedded JPEG preview — standard since TIFF 6.0.
    Supports both little-endian (II) and big-endian (MM) byte orders.
    Returns JPEG bytes on success, None if not found or on parse error.
    """
    import struct
    if len(data) < 8:
        return None
    if data[:2] == b"II":
        bo = "<"
    elif data[:2] == b"MM":
        bo = ">"
    else:
        return None
    magic = struct.unpack_from(bo + "H", data, 2)[0]
    if magic not in (42, 43):  # classic TIFF or BigTIFF
        return None
    try:
        ifd_offset = struct.unpack_from(bo + "I", data, 4)[0]
        num_entries = struct.unpack_from(bo + "H", data, ifd_offset)[0]
        jpeg_offset = jpeg_length = 0
        for i in range(num_entries):
            entry_off = ifd_offset + 2 + i * 12
            tag = struct.unpack_from(bo + "H", data, entry_off)[0]
            val = struct.unpack_from(bo + "I", data, entry_off + 8)[0]
            if tag == 513:    # JPEGInterchangeFormat
                jpeg_offset = val
            elif tag == 514:  # JPEGInterchangeFormatLength
                jpeg_length = val
        if jpeg_offset and jpeg_length:
            thumb = data[jpeg_offset: jpeg_offset + jpeg_length]
            if thumb[:2] == b"\xff\xd8":  # JPEG SOI marker
                return thumb
    except Exception:
        pass
    return None


def _make_svg_placeholder(filename: str, size_bytes: int, media_type: str) -> bytes:
    """Return a browser-renderable SVG placeholder for non-displayable image formats."""
    import html as _html
    ext = media_type.split("/")[-1].upper() if "/" in media_type else "IMG"
    kb = size_bytes / 1024
    name_safe = _html.escape(Path(filename).name[:32])
    size_str = f"{kb:.0f} KB" if kb < 1024 else f"{kb/1024:.1f} MB"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="220">'
        '<rect width="300" height="220" fill="#ede8e2" rx="6"/>'
        '<rect x="90" y="35" width="120" height="100" rx="4" fill="#c8bfb4"/>'
        '<rect x="100" y="45" width="100" height="80" rx="2" fill="#f5f0eb"/>'
        f'<text x="150" y="100" text-anchor="middle" font-family="monospace" '
        f'font-size="22" font-weight="bold" fill="#7a6f65">{ext}</text>'
        f'<text x="150" y="158" text-anchor="middle" font-family="sans-serif" '
        f'font-size="10" fill="#6a6058">{name_safe}</text>'
        f'<text x="150" y="175" text-anchor="middle" font-family="sans-serif" '
        f'font-size="9" fill="#9a9088">{size_str}</text>'
        '</svg>'
    )
    return svg.encode("utf-8")


@router.get("/api/images/{img_id}/thumb")
async def image_thumb(img_id: str):
    """
    Serve a browser-displayable thumbnail for any uploaded image format.

    - JPEG / PNG / WebP: served directly (browsers support these natively).
    - TIFF: attempts to extract an embedded JPEG thumbnail from the TIFF IFD
      (tags 513/514). Falls back to an SVG placeholder if no JPEG preview
      is embedded.
    """
    img = _uploaded_images.get(img_id)
    if not img:
        return JSONResponse({"error": "Nicht gefunden"}, 404)
    img_path = Path(img["path"])
    if not img_path.exists():
        return JSONResponse({"error": "Datei nicht gefunden"}, 404)

    mime = img["media_type"]
    data = img_path.read_bytes()

    # Browser-native formats — serve as-is
    if mime in ("image/jpeg", "image/png", "image/webp"):
        return Response(content=data, media_type=mime)

    # TIFF — try embedded JPEG preview first
    if mime in ("image/tiff", "image/tif"):
        jpeg_thumb = _extract_tiff_jpeg_thumbnail(data)
        if jpeg_thumb:
            return Response(content=jpeg_thumb, media_type="image/jpeg")
        # No embedded preview → return SVG placeholder
        svg = _make_svg_placeholder(img["filename"], img["size_bytes"], mime)
        return Response(content=svg, media_type="image/svg+xml")

    # Unknown format — SVG placeholder
    svg = _make_svg_placeholder(img["filename"], img["size_bytes"], mime)
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/api/images")
async def images_list():
    """List all uploaded images and their analysis status."""
    return {
        "images": [
            {
                "id": img["id"], "filename": img["filename"],
                "size_bytes": img["size_bytes"], "analyzed": img["analyzed"],
                "result": img["result"],
            }
            for img in _uploaded_images.values()
        ]
    }


@router.post("/api/images/analyze")
async def images_analyze(request: dict):
    """
    Run LLM vision analysis on one or more uploaded images.

    Request body:
        image_ids: list[str]   — IDs from /api/images/upload
        model: str             — optional model override
        system_prompt: str     — optional system prompt override
    """
    image_ids = request.get("image_ids", list(_uploaded_images.keys()))
    mod = request.get("model", "")
    syp = request.get("system_prompt", SYSTEM_VISION_EXPERT_DE)

    if not image_ids:
        return JSONResponse({"error": "Keine Bilder hochgeladen"}, 400)

    prov = get_provider(mod)
    results = []

    for img_id in image_ids:
        img = _uploaded_images.get(img_id)
        if not img:
            results.append({"id": img_id, "error": "Nicht gefunden"})
            continue

        try:
            b64 = base64.b64encode(Path(img["path"]).read_bytes()).decode("ascii")
            data_url = f"data:{img['media_type']};base64,{b64}"
            messages = [
                AIMessage.system(syp),
                AIMessage.user([
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": (
                        "Analysiere dieses Bild für eine GLAM-Museumsdatenbank auf Deutsch. "
                        "Beantworte alle Kategorien so präzise wie möglich. "
                        "Antworte AUSSCHLIESSLICH als valides JSON-Objekt mit diesen Feldern:\n"
                        '{"description": "Kurze Bildbeschreibung (1-3 Sätze)", '
                        '"objects": ["sichtbare Objekte und Gegenstände"], '
                        '"persons": ["Namen oder Beschreibung erkennbarer Personen"], '
                        '"has_persons": true/false, '
                        '"person_count": 0, '
                        '"has_text": true/false, '
                        '"text_type": "Bildunterschrift|Stempel|Handschrift|Druck|Gravur|kein Text", '
                        '"text_readable": true/false, '
                        '"transcription_hint": "Lesbarer Text im Bild oder leer", '
                        '"color_mode": "color|bw|sepia|colorized", '
                        '"material": "Fotopapier|Leinwand|Holz|Metall|Pergament|Papier|unbekannt", '
                        '"medium": "Fotografie|Zeichnung|Gemälde|Druckgrafik|Skulptur|Karte|Dokument|unbekannt", '
                        '"condition": "gut|beschädigt|stark beschädigt|restauriert|unbekannt", '
                        '"iconography": ["Ikonographie-Stichworte z.B. Architektur, Portrait, Landschaft"], '
                        '"orientation": "portrait|landscape|square", '
                        '"estimated_date_range": "z.B. 1880-1920 oder leer", '
                        '"style": "Stilrichtung oder Gattung", '
                        '"period": "Historische Epoche", '
                        '"places": ["erkennbare Orte"], '
                        '"confidence": 0.0}'
                    )},
                ]),
            ]
            resp = prov.complete(messages, model=mod or None, max_tokens=512)

            from kwb.core.utils import try_parse_json
            parsed = try_parse_json(resp.content) or {"description": resp.content}
            img["analyzed"] = True
            img["result"] = parsed
            results.append({"id": img_id, "filename": img["filename"], "result": parsed})

            # Persist to workspace
            from datetime import datetime
            ws = get_workspace()
            ws.save_image_analysis(ImageAnalysisResult(
                image_id=img_id,
                filename=img["filename"],
                media_type=img["media_type"],
                analyzed=True,
                result=parsed,
                model=mod or "default",
                analyzed_at=datetime.utcnow().isoformat(),
            ))

        except Exception as e:
            results.append({"id": img_id, "error": str(e)})

    ws = get_workspace()
    ws.log_ai_run("image_analysis", mod or "vision", len(results),
                  len([r for r in results if "result" in r]))

    return {
        "total": len(image_ids),
        "analyzed": len([r for r in results if "result" in r]),
        "model": mod or "default",
        "results": results,
    }


@router.delete("/api/images")
async def images_clear():
    """Clear all uploaded images from memory and disk."""
    count = len(_uploaded_images)
    for img in _uploaded_images.values():
        p = Path(img["path"])
        if p.exists():
            p.unlink(missing_ok=True)
    _uploaded_images.clear()
    return {"cleared": count}


# ---------------------------------------------------------------------------
# OCR / HTR analysis (F30)
# ---------------------------------------------------------------------------

@router.post("/api/images/ocr")
async def images_ocr(request: dict):
    """
    Run OCR/HTR text recognition on uploaded images using vision LLM (F30).

    Request body:
        image_ids: list[str]    -- IDs from /api/images/upload (all if empty)
        model: str              -- optional model override
        additional_context: str -- optional context for OCR prompt
    """
    from kwb.ai.prompts import prompt_ocr_analysis
    from kwb.core.utils import try_parse_json

    image_ids = request.get("image_ids", list(_uploaded_images.keys()))
    mod = request.get("model", "")
    ctx = request.get("additional_context", "")

    if not image_ids:
        return JSONResponse({"error": "Keine Bilder hochgeladen"}, 400)

    prov = get_provider(mod)
    results = []

    for img_id in image_ids:
        img = _uploaded_images.get(img_id)
        if not img:
            results.append({"id": img_id, "error": "Nicht gefunden"})
            continue

        try:
            b64 = base64.b64encode(Path(img["path"]).read_bytes()).decode("ascii")
            data_url = f"data:{img['media_type']};base64,{b64}"

            # Build OCR prompt with image prepended
            ocr_msgs = prompt_ocr_analysis(additional_context=ctx or img["filename"])
            # Replace the user message to include image
            ocr_msgs[1] = AIMessage.user([
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": ocr_msgs[1].content},
            ])

            resp = prov.complete(ocr_msgs, model=mod or None, max_tokens=1024)
            parsed = try_parse_json(resp.content) or {
                "text_found": False,
                "transcription": resp.content,
                "overall_confidence": 0.0,
            }
            results.append({
                "id": img_id,
                "filename": img["filename"],
                "result": parsed,
            })
        except Exception as e:
            results.append({"id": img_id, "error": str(e)})

    successful = [r for r in results if "result" in r]
    return {
        "total": len(image_ids),
        "processed": len(successful),
        "model": mod or "default",
        "results": results,
    }
