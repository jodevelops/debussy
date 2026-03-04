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

# Use a fixed sub-directory of the system temp dir so images survive
# server restarts / hot-reloads.  Created once per process lifetime.
_IMAGE_DIR = Path(_tempfile.gettempdir()) / "debussy_uploads"
_IMAGE_DIR.mkdir(exist_ok=True)

# In-memory metadata index (rebuilt from disk on demand, see _sync_index)
_uploaded_images: dict[str, dict] = {}


def _sync_index() -> None:
    """Re-populate the metadata index from files on disk (called at import time)."""
    ext_to_mime = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".tif": "image/tiff",
        ".tiff": "image/tiff", ".webp": "image/webp",
    }
    for p in sorted(_IMAGE_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in ext_to_mime:
            img_id = p.stem
            if img_id not in _uploaded_images:
                _uploaded_images[img_id] = {
                    "id": img_id,
                    "filename": p.name,
                    "media_type": ext_to_mime[p.suffix.lower()],
                    "size_bytes": p.stat().st_size,
                    "path": str(p),
                    "analyzed": False,
                    "result": None,
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
    """Serve raw image bytes so the browser can display thumbnails."""
    img = _uploaded_images.get(img_id)
    if not img:
        return JSONResponse({"error": "Nicht gefunden"}, 404)
    img_path = Path(img["path"])
    if not img_path.exists():
        return JSONResponse({"error": "Datei nicht gefunden"}, 404)
    return Response(content=img_path.read_bytes(), media_type=img["media_type"])


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
                        "Beschreibe dieses Bild für eine Museumsdatenbank auf Deutsch. "
                        "Identifiziere sichtbare Objekte, Personen, Orte und Stilmerkmale. "
                        'Antworte als JSON: {"description": "...", "objects": [], '
                        '"persons": [], "places": [], "style": "...", "period": "...", "confidence": 0.0}'
                    )},
                ]),
            ]
            resp = prov.complete(messages, model=mod or None, max_tokens=512)

            from kwb.core.utils import try_parse_json
            parsed = try_parse_json(resp.content) or {"description": resp.content}
            img["analyzed"] = True
            img["result"] = parsed
            results.append({"id": img_id, "filename": img["filename"], "result": parsed})

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
