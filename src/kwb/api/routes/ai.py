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
import tempfile
from pathlib import Path

try:
    from fastapi import APIRouter, File, UploadFile
    from fastapi.responses import JSONResponse, Response
except ImportError:
    raise ImportError("pip install fastapi uvicorn python-multipart")

from kwb.api.deps import (
    ALLOWED_IMAGE_EXT, MAX_FILE_BYTES, MAX_UPLOAD_FILES,
    get_config, get_datasets, get_provider, get_state, get_workspace,
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
async def gpu_test(request: dict):
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
async def ai_describe_columns(request: dict):
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
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

    return {"descriptions": descriptions, "model": mod or "default"}


# ---------------------------------------------------------------------------
# Image analysis
# ---------------------------------------------------------------------------

# In-process image store (keyed by upload session)
_uploaded_images: dict[str, dict] = {}


@router.post("/api/images/upload")
async def images_upload(files: list[UploadFile] = File(...)):
    """
    Upload image files for visual analysis.

    Accepted formats: JPEG, PNG, TIFF, WebP.
    Returns a list of image handles (id + filename + preview dimensions).
    """
    if len(files) > MAX_UPLOAD_FILES:
        return JSONResponse({"error": f"Max {MAX_UPLOAD_FILES} Bilder"}, 400)

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
        _uploaded_images[img_id] = {
            "id": img_id,
            "filename": u.filename,
            "media_type": media_type,
            "size_bytes": len(content),
            "b64": base64.b64encode(content).decode("ascii"),
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


@router.get("/api/images/{img_id}")
async def images_serve(img_id: str):
    """Serve a single uploaded image as binary with correct Content-Type."""
    img = _uploaded_images.get(img_id)
    if not img:
        return JSONResponse({"error": "Nicht gefunden"}, 404)
    raw = base64.b64decode(img["b64"])
    return Response(content=raw, media_type=img["media_type"])


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
            data_url = f"data:{img['media_type']};base64,{img['b64']}"
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
    """Clear all uploaded images from memory."""
    count = len(_uploaded_images)
    _uploaded_images.clear()
    return {"cleared": count}
