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

import json

try:
    from fastapi import APIRouter, File, UploadFile
    from fastapi.responses import JSONResponse, Response, StreamingResponse
except ImportError:
    raise ImportError("pip install fastapi uvicorn python-multipart")

from kwb.api.deps import (
    ALLOWED_IMAGE_EXT, MAX_FILE_BYTES, MAX_IMAGE_FILES,
    get_config, get_datasets, get_provider, get_workspace,
    set_config, workspace_dir, safe_filename,
)
from kwb.ai.provider import AIMessage
from kwb.ai.batch import process_batch
from kwb.ai.prompts import SYSTEM_METADATA_EXPERT_DE
from kwb.core.workspace import ImageAnalysisResult, ImageReviewStatus
from kwb.ai.prompts import (
    PROMPT_VERSIONS,
    prompt_image_description,
    prompt_person_face_visibility,
    prompt_ocr_transcription_quality,
)
from kwb.ingest.image_loader import ingest_image

router = APIRouter()


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _parse_image_review_status(status_raw: str) -> ImageReviewStatus | None:
    try:
        return ImageReviewStatus(status_raw)
    except ValueError:
        return None

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
        config = {"gpustack_model_text": c.gpustack_model_text, "gpustack_model_vision": c.gpustack_model_vision}
        return {"status": "ok" if available else "error",
                "configured": True, "available": available, "models": models, "config": config}
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
# GPU / Provider configuration (read + update)
# ---------------------------------------------------------------------------

@router.get("/api/gpu/config")
async def gpu_config_get():
    """Return current GPUStack config (API key masked)."""
    from kwb.core.utils import mask_secret
    c = get_config()
    return {
        "gpustack_url": c.gpustack_url,
        "gpustack_key_masked": mask_secret(c.gpustack_key) if c.gpustack_key else "",
        "gpustack_model_text": c.gpustack_model_text,
        "gpustack_model_vision": c.gpustack_model_vision,
    }


@router.post("/api/gpu/config")
async def gpu_config_set(request: dict):
    """Update GPUStack connection settings and persist to .env."""
    from dataclasses import replace as dc_replace
    c = get_config()

    new_url = (request.get("gpustack_url") or "").strip()
    new_key = (request.get("gpustack_key") or "").strip()
    new_mt = (request.get("gpustack_model_text") or "").strip()
    new_mv = (request.get("gpustack_model_vision") or "").strip()

    # Only the API key uses "empty = keep existing" semantics (it's a secret).
    # URL and model fields can be explicitly cleared by submitting an empty string.
    gpustack_key = new_key if new_key else c.gpustack_key
    updated = dc_replace(
        c,
        gpustack_url=new_url,
        gpustack_key=gpustack_key,
        gpustack_model_text=new_mt,
        gpustack_model_vision=new_mv,
    )
    # Persist to disk first — if writing fails, in-memory config stays unchanged.
    try:
        updated.save_to_dotenv()
    except Exception as e:
        return JSONResponse({"status": "error", "message": f".env speichern fehlgeschlagen: {e}"}, 500)
    set_config(updated)
    return {"status": "ok"}


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
            descriptions[col] = {"column": col, "description": br.response.content if br.response else "", "data_type": "unbekannt"}

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


def _image_exif_subset(exif: dict | None) -> dict:
    """Return a compact EXIF subset useful for review/export."""
    if not exif:
        return {}
    keys = ("DateTime", "DateTimeOriginal", "Make", "Model", "Orientation", "Artist")
    return {k: exif[k] for k in keys if k in exif and exif[k] not in (None, "")}


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
                    "media_type": ws_result.media_type if ws_result and ws_result.media_type else ext_to_mime[p.suffix.lower()],
                    "size_bytes": ws_result.size_bytes if ws_result and ws_result.size_bytes else p.stat().st_size,
                    "width": ws_result.width if ws_result else None,
                    "height": ws_result.height if ws_result else None,
                    "hash_sha256": ws_result.hash_sha256 if ws_result else "",
                    "exif_subset": ws_result.exif_subset if ws_result else {},
                    "path": str(p),
                    "analyzed": ws_result.analyzed if ws_result else False,
                    "result": ws_result.result if ws_result else None,
                    "record_id": ws_result.record_id if ws_result else "",
                    "review_status": ws_result.review_status.value if ws_result else "pending",
                    "review_comment": ws_result.review_comment if ws_result else "",
                    "reviewer": ws_result.reviewer if ws_result else "",
                    "reviewed_at": ws_result.reviewed_at if ws_result else "",
                }


_sync_index()

# Remove stale entries whose files no longer exist on disk
_stale = [k for k, v in _uploaded_images.items() if not Path(v["path"]).exists()]
for _k in _stale:
    del _uploaded_images[_k]

def _vision_prompt_for_task(task: str, context: str = ""):
    if task == "person_face_visibility":
        return prompt_person_face_visibility(additional_context=context)
    return prompt_image_description(additional_context=context)


def _prompt_meta(task: str) -> tuple[str, str]:
    return task, PROMPT_VERSIONS.get(task, "custom")


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

        img_id = f"img_{len(_uploaded_images) + 1:04d}_{Path(u.filename).stem}"
        img_path = _IMAGE_DIR / f"{img_id}{suffix}"
        img_path.write_bytes(content)

        profile = ingest_image(img_path, load_base64=False)
        exif_subset = _image_exif_subset(profile.exif)
        media_type = profile.mime_type or {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".tif": "image/tiff",
            ".tiff": "image/tiff", ".webp": "image/webp",
        }.get(suffix, "image/jpeg")

        _uploaded_images[img_id] = {
            "id": img_id,
            "filename": u.filename,
            "media_type": media_type,
            "size_bytes": profile.file_size_bytes,
            "width": profile.width,
            "height": profile.height,
            "hash_sha256": profile.hash_sha256,
            "exif_subset": exif_subset,
            "path": str(img_path),
            "analyzed": False,
            "result": None,
            "record_id": "",
            "review_status": "pending",
            "review_comment": "",
            "reviewer": "",
            "reviewed_at": "",
        }
        accepted.append({
            "id": img_id,
            "filename": u.filename,
            "size_bytes": profile.file_size_bytes,
            "media_type": media_type,
            "width": profile.width,
            "height": profile.height,
            "hash_sha256": profile.hash_sha256,
            "exif_subset": exif_subset,
            "analyzed": False,
            "result": None,
            "record_id": "",
            "review_status": "pending",
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
    # Filter out stale entries whose files no longer exist
    stale_ids = [k for k, img in _uploaded_images.items() if not Path(img["path"]).exists()]
    for sid in stale_ids:
        del _uploaded_images[sid]
    return {
        "images": [
            {
                "id": img["id"], "filename": img["filename"],
                "media_type": img["media_type"],
                "size_bytes": img["size_bytes"],
                "width": img.get("width"), "height": img.get("height"),
                "hash_sha256": img.get("hash_sha256", ""),
                "exif_subset": img.get("exif_subset", {}),
                "analyzed": img["analyzed"],
                "result": img["result"],
                "record_id": img.get("record_id", ""),
                "review_status": img.get("review_status", "pending"),
                "review_comment": img.get("review_comment", ""),
                "reviewer": img.get("reviewer", ""),
                "reviewed_at": img.get("reviewed_at", ""),
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
        prompt_task: str       — image_description | person_face_visibility
        boolean_params: list[str] — boolean yes/no questions to append
            Default: ["Are there humans in the image?",
                      "Are their faces recognizable?"]
    """
    from kwb.core.utils import try_parse_json, utc_now_iso

    image_ids = request.get("image_ids", list(_uploaded_images.keys()))
    image_record_map = request.get("image_record_map", {})
    mod = request.get("model", "")
    task = request.get("prompt_task", "image_description")
    syp = request.get("system_prompt", "")
    bool_params = request.get("boolean_params", [])

    if not image_ids:
        return JSONResponse({"error": "Keine Bilder hochgeladen"}, 400)

    prov = get_provider(mod)
    results = []
    prompt_name, prompt_version = _prompt_meta(task)

    for img_id in image_ids:
        img = _uploaded_images.get(img_id)
        if not img:
            results.append({"id": img_id, "error": "Nicht gefunden"})
            continue

        try:
            b64 = base64.b64encode(Path(img["path"]).read_bytes()).decode("ascii")
            data_url = f"data:{img['media_type']};base64,{b64}"
            ctx = request.get("additional_context", "") or img["filename"]
            prompt_msgs = _vision_prompt_for_task(task, context=ctx)
            if syp:
                prompt_msgs[0] = AIMessage.system(syp)

            # Append boolean analysis parameters
            bool_suffix = ""
            if bool_params:
                bool_suffix = (
                    "\n\nAdditionally, answer each of the following "
                    "questions with TRUE or FALSE:\n"
                )
                for bp in bool_params:
                    bool_suffix += f"- {bp}\n"
                bool_suffix += (
                    '\nInclude a "boolean_analysis" object in your '
                    "JSON with each question as key and true/false "
                    "as value."
                )

            prompt_text = prompt_msgs[1].content + bool_suffix
            prompt_msgs[1] = AIMessage.user([
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": prompt_text},
            ])

            resp = prov.complete(prompt_msgs, model=mod or None, max_tokens=900)
            parsed = try_parse_json(resp.content) or {"description": resp.content, "uncertain": True}
            img["analyzed"] = True
            img["result"] = parsed
            img["record_id"] = image_record_map.get(img_id, img.get("record_id", ""))
            results.append({
                "id": img_id,
                "filename": img["filename"],
                "record_id": img.get("record_id", ""),
                "review_status": img.get("review_status", "pending"),
                "result": parsed,
            })

            ws = get_workspace()
            ws.save_image_analysis(ImageAnalysisResult(
                image_id=img_id,
                filename=img["filename"],
                media_type=img["media_type"],
                size_bytes=img.get("size_bytes", 0),
                width=img.get("width"),
                height=img.get("height"),
                hash_sha256=img.get("hash_sha256", ""),
                exif_subset=img.get("exif_subset", {}),
                analyzed=True,
                result=parsed,
                model=mod or "default",
                analyzed_at=utc_now_iso(),
                record_id=img.get("record_id", ""),
                review_status=ImageReviewStatus(img.get("review_status", "pending")),
                review_comment=img.get("review_comment", ""),
                reviewer=img.get("reviewer", ""),
                reviewed_at=img.get("reviewed_at", ""),
                prompt_name=prompt_name,
                prompt_version=prompt_version,
            ))
            ws.save(workspace_dir() / safe_filename(ws.name))

        except Exception as e:
            results.append({"id": img_id, "error": str(e)})

    ws = get_workspace()
    ws.log_ai_run(
        "image_analysis", mod or "vision", len(results),
        len([r for r in results if "result" in r]),
        prompt_name=prompt_name,
        prompt_version=prompt_version,
    )

    return {
        "total": len(image_ids),
        "analyzed": len([r for r in results if "result" in r]),
        "model": mod or "default",
        "prompt_name": prompt_name,
        "prompt_version": prompt_version,
        "results": results,
        "ai_provenance": {
            "model": mod or "default",
            "prompt_name": prompt_name,
            "prompt_version": prompt_version,
            "task": task,
        },
    }


@router.post("/api/images/analyze/stream")
async def images_analyze_stream(request: dict):
    """SSE streaming version of /api/images/analyze — yields progress per image."""
    from kwb.core.utils import try_parse_json, utc_now_iso

    image_ids = request.get("image_ids", list(_uploaded_images.keys()))
    image_record_map = request.get("image_record_map", {})
    mod = request.get("model", "")
    task = request.get("prompt_task", "image_description")
    syp = request.get("system_prompt", "")

    if not image_ids:
        return JSONResponse({"error": "Keine Bilder hochgeladen"}, 400)

    prov = get_provider(mod)
    prompt_name, prompt_version = _prompt_meta(task)
    total = len(image_ids)

    async def generate():
        results = []
        for idx, img_id in enumerate(image_ids, 1):
            img = _uploaded_images.get(img_id)
            if not img:
                results.append({"id": img_id, "error": "Nicht gefunden"})
                yield _sse_event({
                    "type": "progress", "current": idx, "total": total,
                    "filename": img_id,
                })
                continue

            try:
                b64 = base64.b64encode(
                    Path(img["path"]).read_bytes()
                ).decode("ascii")
                data_url = f"data:{img['media_type']};base64,{b64}"
                ctx = request.get("additional_context", "") or img["filename"]
                prompt_msgs = _vision_prompt_for_task(task, context=ctx)
                if syp:
                    prompt_msgs[0] = AIMessage.system(syp)
                prompt_msgs[1] = AIMessage.user([
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt_msgs[1].content},
                ])

                resp = prov.complete(prompt_msgs, model=mod or None, max_tokens=900)
                parsed = try_parse_json(resp.content) or {
                    "description": resp.content, "uncertain": True,
                }
                img["analyzed"] = True
                img["result"] = parsed
                img["record_id"] = image_record_map.get(
                    img_id, img.get("record_id", ""),
                )
                results.append({
                    "id": img_id, "filename": img["filename"],
                    "record_id": img.get("record_id", ""),
                    "review_status": img.get("review_status", "pending"),
                    "result": parsed,
                })

                ws = get_workspace()
                ws.save_image_analysis(ImageAnalysisResult(
                    image_id=img_id,
                    filename=img["filename"],
                    media_type=img["media_type"],
                    size_bytes=img.get("size_bytes", 0),
                    width=img.get("width"),
                    height=img.get("height"),
                    hash_sha256=img.get("hash_sha256", ""),
                    exif_subset=img.get("exif_subset", {}),
                    analyzed=True,
                    result=parsed,
                    model=mod or "default",
                    analyzed_at=utc_now_iso(),
                    record_id=img.get("record_id", ""),
                    review_status=ImageReviewStatus(
                        img.get("review_status", "pending")
                    ),
                    review_comment=img.get("review_comment", ""),
                    reviewer=img.get("reviewer", ""),
                    reviewed_at=img.get("reviewed_at", ""),
                    prompt_name=prompt_name,
                    prompt_version=prompt_version,
                ))
                ws.save(workspace_dir() / safe_filename(ws.name))

            except Exception as e:
                results.append({"id": img_id, "error": str(e)})

            yield _sse_event({
                "type": "progress", "current": idx, "total": total,
                "filename": img.get("filename", img_id) if img else img_id,
            })

        ws = get_workspace()
        ws.log_ai_run(
            "image_analysis", mod or "vision", len(results),
            len([r for r in results if "result" in r]),
            prompt_name=prompt_name, prompt_version=prompt_version,
        )
        yield _sse_event({
            "type": "done",
            "result": {
                "total": total,
                "analyzed": len([r for r in results if "result" in r]),
                "model": mod or "default",
                "prompt_name": prompt_name,
                "prompt_version": prompt_version,
                "results": results,
                "ai_provenance": {
                    "model": mod or "default",
                    "prompt_name": prompt_name,
                    "prompt_version": prompt_version,
                    "task": task,
                },
            },
        })

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/api/images/{img_id}/review")
async def image_review_update(img_id: str, request: dict):
    """Update review decision and optional corrected result for one image analysis."""
    img = _uploaded_images.get(img_id)
    if not img:
        return JSONResponse({"error": "Nicht gefunden"}, 404)

    status_raw = request.get("status", "pending")
    status = _parse_image_review_status(status_raw)
    if status is None:
        return JSONResponse({"error": "Ungültiger Review-Status"}, 400)

    comment = request.get("comment", "")
    reviewer = request.get("reviewer", "")
    result_updates = request.get("result_updates") or {}
    record_id = request.get("record_id", img.get("record_id", ""))

    if result_updates:
        if not isinstance(img.get("result"), dict):
            img["result"] = {}
        img["result"].update(result_updates)

    img["record_id"] = record_id
    img["review_status"] = status.value
    img["review_comment"] = comment
    img["reviewer"] = reviewer
    from kwb.core.utils import utc_now_iso
    img["reviewed_at"] = utc_now_iso()

    ws = get_workspace()
    existing = ws.get_image_analysis(img_id)
    if existing:
        existing.result = img.get("result") or {}
        existing.record_id = record_id
        existing.update_review(
            status=status,
            comment=comment,
            reviewer=reviewer,
        )
        ws.save_image_analysis(existing)
    else:
        ana = ImageAnalysisResult(
            image_id=img_id,
            filename=img.get("filename", ""),
            media_type=img.get("media_type", ""),
            analyzed=bool(img.get("analyzed")),
            result=img.get("result") or {},
            model="manual",
            analyzed_at="",
            record_id=record_id,
            review_status=status,
            review_comment=comment,
            reviewer=reviewer,
            reviewed_at=img["reviewed_at"],
        )
        ws.save_image_analysis(ana)

    ws.save(workspace_dir() / safe_filename(ws.name))

    return {
        "ok": True,
        "image": {
            "id": img_id,
            "record_id": img["record_id"],
            "review_status": img["review_status"],
            "review_comment": img["review_comment"],
            "reviewer": img["reviewer"],
            "reviewed_at": img["reviewed_at"],
            "result": img.get("result") or {},
        },
    }




@router.post("/api/images/review/batch")
async def image_review_batch(request: dict):
    """Batch-update review decisions for multiple image analyses."""
    image_ids = request.get("image_ids", [])
    if not image_ids:
        return JSONResponse({"error": "Keine Bilder ausgewählt"}, 400)

    status_raw = request.get("status", "pending")
    status = _parse_image_review_status(status_raw)
    if status is None:
        return JSONResponse({"error": "Ungültiger Review-Status"}, 400)

    comment = request.get("comment", "")
    reviewer = request.get("reviewer", "")

    ws = get_workspace()
    updated = 0
    from kwb.core.utils import utc_now_iso

    for img_id in image_ids:
        img = _uploaded_images.get(img_id)
        if not img:
            continue

        img["review_status"] = status.value
        if comment:
            img["review_comment"] = comment
        if reviewer:
            img["reviewer"] = reviewer
        img["reviewed_at"] = utc_now_iso()

        existing = ws.get_image_analysis(img_id)
        if existing:
            existing.update_review(
                status=status,
                comment=img.get("review_comment", ""),
                reviewer=img.get("reviewer", ""),
            )
            ws.save_image_analysis(existing)
            updated += 1

    ws.save(workspace_dir() / safe_filename(ws.name))
    return {"updated": updated, "status": status.value}

@router.post("/api/images/review/sample")
async def image_review_sample(request: dict):
    """Return a spot-check sample of pending OCR results for review."""
    ws = get_workspace()
    sample_size = min(request.get("sample_size", 10), 100)
    strategy = request.get("strategy", "random")

    pending = [
        r for r in ws.image_analyses
        if r.review_status == ImageReviewStatus.PENDING and r.analyzed
    ]
    total_pending = len(pending)

    if strategy == "low_confidence":
        pending.sort(key=lambda r: r.confidence)
    else:
        import random
        random.shuffle(pending)

    sample = pending[:sample_size]
    return {
        "sample": [r.to_dict() for r in sample],
        "total_pending": total_pending,
        "sample_size": len(sample),
        "strategy": strategy,
    }


@router.post("/api/images/review/auto-accept")
async def image_review_auto_accept(request: dict):
    """Auto-accept all OCR results with confidence >= min_confidence."""
    ws = get_workspace()
    min_confidence = float(request.get("min_confidence", 0.85))

    auto_accepted = 0
    for analysis in ws.image_analyses:
        if analysis.review_status != ImageReviewStatus.PENDING:
            continue
        if not analysis.analyzed:
            continue
        if analysis.confidence >= min_confidence:
            analysis.update_review(
                status=ImageReviewStatus.ACCEPTED,
                comment=f"Auto-accepted (confidence {analysis.confidence:.2f} >= {min_confidence})",
                reviewer="auto",
            )
            # Also update in-memory image index
            img = _uploaded_images.get(analysis.image_id)
            if img:
                img["review_status"] = "accepted"
                img["review_comment"] = analysis.review_comment
                img["reviewed_at"] = analysis.reviewed_at
            auto_accepted += 1

    remaining = sum(
        1 for r in ws.image_analyses
        if r.review_status == ImageReviewStatus.PENDING
    )

    ws.save(workspace_dir() / safe_filename(ws.name))
    return {
        "auto_accepted": auto_accepted,
        "remaining_pending": remaining,
        "min_confidence": min_confidence,
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
    from kwb.core.utils import try_parse_json

    image_ids = request.get("image_ids", list(_uploaded_images.keys()))
    image_record_map = request.get("image_record_map", {})
    mod = request.get("model", "")
    ctx = request.get("additional_context", "")
    syp = request.get("system_prompt", "")

    if not image_ids:
        return JSONResponse({"error": "Keine Bilder hochgeladen"}, 400)

    prov = get_provider(mod)
    results = []
    prompt_name, prompt_version = _prompt_meta("ocr_transcription_quality")

    for img_id in image_ids:
        img = _uploaded_images.get(img_id)
        if not img:
            results.append({"id": img_id, "error": "Nicht gefunden"})
            continue

        try:
            b64 = base64.b64encode(Path(img["path"]).read_bytes()).decode("ascii")
            data_url = f"data:{img['media_type']};base64,{b64}"

            ocr_msgs = prompt_ocr_transcription_quality(additional_context=ctx or img["filename"])
            if syp:
                ocr_msgs[0] = AIMessage.system(syp)
            ocr_msgs[1] = AIMessage.user([
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": ocr_msgs[1].content},
            ])

            resp = prov.complete(ocr_msgs, model=mod or None, max_tokens=1200)
            parsed = try_parse_json(resp.content) or {
                "text_found": False,
                "transcription": resp.content,
                "overall_confidence": 0.0,
                "uncertain": True,
            }
            results.append({
                "id": img_id,
                "filename": img["filename"],
                "result": parsed,
            })
        except Exception as e:
            results.append({"id": img_id, "error": str(e)})

    successful = [r for r in results if "result" in r]
    ws = get_workspace()

    # Persist OCR results in workspace image_analyses for OCR→NER pipeline
    from kwb.core.utils import utc_now_iso
    for r in successful:
        img = _uploaded_images.get(r["id"])
        if not img:
            continue
        record_id = image_record_map.get(r["id"], img.get("record_id", ""))
        existing = ws.get_image_analysis(r["id"])
        if existing:
            existing.result = existing.result or {}
            existing.result.update(r["result"])
            existing.record_id = record_id
        else:
            ws.save_image_analysis(ImageAnalysisResult(
                image_id=r["id"],
                filename=img.get("filename", ""),
                media_type=img.get("media_type", ""),
                analyzed=True,
                result=r["result"],
                model=mod or "default",
                analyzed_at=utc_now_iso(),
                record_id=record_id,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
            ))

    ws.log_ai_run(
        "image_ocr", mod or "vision", len(image_ids), len(successful),
        prompt_name=prompt_name,
        prompt_version=prompt_version,
    )
    return {
        "total": len(image_ids),
        "processed": len(successful),
        "model": mod or "default",
        "prompt_name": prompt_name,
        "prompt_version": prompt_version,
        "results": results,
        "ai_provenance": {
            "model": mod or "default",
            "prompt_name": prompt_name,
            "prompt_version": prompt_version,
        },
    }


@router.post("/api/images/review")
async def review_image_ai(request: dict):
    """Simple expert review workflow for image AI suggestions."""
    ws = get_workspace()
    image_id = request.get("image_id", "")
    status = request.get("status", "pending")
    note = request.get("note", "")
    if status not in {"pending", "approved", "rejected"}:
        return JSONResponse({"error": "status must be pending|approved|rejected"}, 400)

    target = ws.get_image_analysis(image_id)
    if not target:
        return JSONResponse({"error": "Bildanalyse nicht gefunden"}, 404)

    from kwb.core.utils import utc_now_iso
    target.review_status = status
    target.review_note = note
    target.reviewed_at = utc_now_iso() if status != "pending" else ""
    ws.save(workspace_dir() / safe_filename(ws.name))
    return {"ok": True, "image_id": image_id, "review_status": target.review_status, "stats": ws.image_review_stats()}
