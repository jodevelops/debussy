"""
Tests for image upload and analysis endpoints.

Covers:
  - POST /api/images/upload  — JPEG, PNG, TIFF, WebP, invalid format, multi-file
  - GET  /api/images          — list uploaded images
  - POST /api/images/analyze  — vision AI analysis
  - DELETE /api/images        — clear image store

Fake image bytes are minimal stubs that satisfy extension validation.
The upload endpoint checks file extension and size only, not image validity.
"""
from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

_FORCE_NO_FASTAPI = os.environ.get("KWB_FORCE_NO_FASTAPI") == "1"
try:
    if _FORCE_NO_FASTAPI:
        raise ImportError("FastAPI disabled for deterministic catalog checks")
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

_skip = unittest.skipUnless(_FASTAPI_AVAILABLE, "FastAPI not installed")

# ---------------------------------------------------------------------------
# Minimal image stubs (magic bytes only — enough to pass extension checks)
# ---------------------------------------------------------------------------
# JPEG: SOI marker + minimal JFIF APP0 + EOI
_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xd9"
)
# PNG: 8-byte signature + IHDR (1x1 px, 8-bit RGB) + IEND
_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd5N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
# TIFF: little-endian magic + minimal IFD offset (0 entries, no next IFD)
_TIFF = b"II\x2a\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00"
# WebP: RIFF header (minimal VP8L stub)
_WEBP = b"RIFF\x1c\x00\x00\x00WEBPVP8 \x10\x00\x00\x00\x30\x01\x00\x9d\x01\x2a\x01\x00\x01\x00\x00\x34\x25\x9f"


def _img_file(data: bytes, name: str) -> tuple:
    """Build a files-tuple for TestClient.post(files=...)."""
    ext = Path(name).suffix.lstrip(".")
    mime = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png",
        "tif": "image/tiff", "tiff": "image/tiff",
        "webp": "image/webp",
    }.get(ext, "application/octet-stream")
    return ("files", (name, io.BytesIO(data), mime))


def _get_client():
    """Fresh TestClient with reset state and mock provider."""
    from kwb.api import deps
    from kwb.core.workspace import Workspace
    from kwb.ai.mock import MockProvider
    from kwb.api.routes import ai as ai_routes

    deps._state["datasets"] = {}
    deps._state["report"] = None
    deps._state["workspace"] = Workspace(name="test")
    deps._config_cache = None
    deps._prov_override = MockProvider.with_defaults()

    # Reset the module-level image store between tests
    ai_routes._uploaded_images.clear()

    from kwb.api.app import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Upload tests
# ---------------------------------------------------------------------------

@_skip
class TestImageUpload(unittest.TestCase):

    def setUp(self):
        self.client = _get_client()

    def test_upload_jpeg(self):
        r = self.client.post("/api/images/upload", files=[_img_file(_JPEG, "photo.jpg")])
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["uploaded"], 1)
        img = data["images"][0]
        self.assertEqual(img["filename"], "photo.jpg")
        self.assertEqual(img["media_type"], "image/jpeg")
        self.assertGreater(img["size_bytes"], 0)

    def test_upload_jpeg_alt_extension(self):
        r = self.client.post("/api/images/upload", files=[_img_file(_JPEG, "scan.jpeg")])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["images"][0]["media_type"], "image/jpeg")

    def test_upload_png(self):
        r = self.client.post("/api/images/upload", files=[_img_file(_PNG, "drawing.png")])
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["uploaded"], 1)
        self.assertEqual(data["images"][0]["media_type"], "image/png")
        self.assertEqual(data["images"][0]["width"], 1)
        self.assertEqual(data["images"][0]["height"], 1)
        self.assertTrue(data["images"][0]["hash_sha256"])

    def test_upload_tiff(self):
        r = self.client.post("/api/images/upload", files=[_img_file(_TIFF, "scan.tif")])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["images"][0]["media_type"], "image/tiff")

    def test_upload_tiff_long_extension(self):
        r = self.client.post("/api/images/upload", files=[_img_file(_TIFF, "archiv.tiff")])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["images"][0]["media_type"], "image/tiff")

    def test_upload_webp(self):
        r = self.client.post("/api/images/upload", files=[_img_file(_WEBP, "thumb.webp")])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["images"][0]["media_type"], "image/webp")

    def test_upload_multiple_formats(self):
        r = self.client.post("/api/images/upload", files=[
            _img_file(_JPEG, "a.jpg"),
            _img_file(_PNG, "b.png"),
            _img_file(_TIFF, "c.tif"),
            _img_file(_WEBP, "d.webp"),
        ])
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["uploaded"], 4)
        types = {img["media_type"] for img in data["images"]}
        self.assertIn("image/jpeg", types)
        self.assertIn("image/png", types)
        self.assertIn("image/tiff", types)
        self.assertIn("image/webp", types)

    def test_upload_invalid_format_rejected(self):
        r = self.client.post("/api/images/upload", files=[
            ("files", ("document.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf"))
        ])
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.json())

    def test_upload_returns_unique_ids(self):
        r = self.client.post("/api/images/upload", files=[
            _img_file(_JPEG, "x.jpg"),
            _img_file(_PNG, "y.png"),
        ])
        ids = [img["id"] for img in r.json()["images"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_upload_with_folder_path_in_filename(self):
        """Simulate folder upload where filename includes relative path."""
        r = self.client.post("/api/images/upload", files=[
            ("files", ("2024/januar/foto.jpg", io.BytesIO(_JPEG), "image/jpeg")),
        ])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["uploaded"], 1)


# ---------------------------------------------------------------------------
# List tests
# ---------------------------------------------------------------------------

@_skip
class TestImageList(unittest.TestCase):

    def setUp(self):
        self.client = _get_client()

    def test_list_empty(self):
        r = self.client.get("/api/images")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["images"], [])

    def test_list_after_upload(self):
        self.client.post("/api/images/upload", files=[
            _img_file(_JPEG, "a.jpg"),
            _img_file(_PNG, "b.png"),
        ])
        r = self.client.get("/api/images")
        self.assertEqual(r.status_code, 200)
        imgs = r.json()["images"]
        self.assertEqual(len(imgs), 2)
        for img in imgs:
            self.assertIn("id", img)
            self.assertIn("filename", img)
            self.assertIn("analyzed", img)
            self.assertIn("width", img)
            self.assertIn("height", img)
            self.assertIn("hash_sha256", img)
            self.assertIn("exif_subset", img)
            self.assertFalse(img["analyzed"])  # not yet analyzed


# ---------------------------------------------------------------------------
# Analyze tests
# ---------------------------------------------------------------------------

@_skip
class TestImageAnalyze(unittest.TestCase):

    def setUp(self):
        self.client = _get_client()

    def _upload_one(self, data=_JPEG, name="test.jpg"):
        r = self.client.post("/api/images/upload", files=[_img_file(data, name)])
        self.assertEqual(r.status_code, 200)
        return r.json()["images"][0]["id"]

    def test_analyze_jpeg(self):
        img_id = self._upload_one(_JPEG, "museum.jpg")
        r = self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["analyzed"], 1)
        res = data["results"][0]
        self.assertEqual(res["id"], img_id)
        self.assertIn("result", res)

    def test_analyze_png(self):
        img_id = self._upload_one(_PNG, "zeichnung.png")
        r = self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["analyzed"], 1)

    def test_analyze_tiff(self):
        img_id = self._upload_one(_TIFF, "scan.tif")
        r = self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["analyzed"], 1)

    def test_analyze_webp(self):
        img_id = self._upload_one(_WEBP, "thumb.webp")
        r = self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["analyzed"], 1)

    def test_analyze_all_formats_batch(self):
        ids = []
        for data, name in [(_JPEG, "a.jpg"), (_PNG, "b.png"), (_TIFF, "c.tif"), (_WEBP, "d.webp")]:
            r = self.client.post("/api/images/upload", files=[_img_file(data, name)])
            ids.append(r.json()["images"][0]["id"])
        r = self.client.post("/api/images/analyze", json={"image_ids": ids})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total"], 4)
        self.assertEqual(data["analyzed"], 4)

    def test_analyze_unknown_id_returns_error_entry(self):
        r = self.client.post("/api/images/analyze", json={"image_ids": ["img_9999_fake"]})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["analyzed"], 0)
        self.assertIn("error", data["results"][0])

    def test_analyze_marks_image_as_analyzed(self):
        img_id = self._upload_one()
        self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        r = self.client.get("/api/images")
        img = next(i for i in r.json()["images"] if i["id"] == img_id)
        self.assertTrue(img["analyzed"])

    def test_analyze_no_images_uploaded(self):
        r = self.client.post("/api/images/analyze", json={"image_ids": []})
        self.assertIn(r.status_code, (400, 422))

    def test_analyze_with_custom_prompt(self):
        img_id = self._upload_one()
        r = self.client.post("/api/images/analyze", json={
            "image_ids": [img_id],
            "system_prompt": "Describe the image.",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["analyzed"], 1)


# ---------------------------------------------------------------------------
# Image data (thumbnail) endpoint tests
# ---------------------------------------------------------------------------

@_skip
class TestImageData(unittest.TestCase):
    """GET /api/images/{img_id}/data — serve raw image bytes for thumbnail display."""

    def setUp(self):
        self.client = _get_client()

    def _upload(self, data: bytes, name: str) -> str:
        r = self.client.post("/api/images/upload", files=[_img_file(data, name)])
        self.assertEqual(r.status_code, 200)
        return r.json()["images"][0]["id"]

    def test_data_jpeg_returns_bytes_and_content_type(self):
        img_id = self._upload(_JPEG, "foto.jpg")
        r = self.client.get(f"/api/images/{img_id}/data")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/jpeg")
        self.assertEqual(r.content, _JPEG)

    def test_data_png_returns_bytes_and_content_type(self):
        img_id = self._upload(_PNG, "zeichnung.png")
        r = self.client.get(f"/api/images/{img_id}/data")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/png")
        self.assertEqual(r.content, _PNG)

    def test_data_tiff_returns_bytes_and_content_type(self):
        img_id = self._upload(_TIFF, "scan.tif")
        r = self.client.get(f"/api/images/{img_id}/data")
        self.assertEqual(r.status_code, 200)
        self.assertIn("image/tiff", r.headers["content-type"])
        self.assertEqual(r.content, _TIFF)

    def test_data_webp_returns_bytes_and_content_type(self):
        img_id = self._upload(_WEBP, "thumb.webp")
        r = self.client.get(f"/api/images/{img_id}/data")
        self.assertEqual(r.status_code, 200)
        self.assertIn("image/webp", r.headers["content-type"])
        self.assertEqual(r.content, _WEBP)

    def test_data_unknown_id_returns_404(self):
        r = self.client.get("/api/images/img_9999_notfound/data")
        self.assertEqual(r.status_code, 404)

    def test_data_survives_analyze(self):
        """Image bytes remain accessible after analysis."""
        img_id = self._upload(_JPEG, "museum.jpg")
        self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        r = self.client.get(f"/api/images/{img_id}/data")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, _JPEG)


# ---------------------------------------------------------------------------
# Full workflow integration tests
# ---------------------------------------------------------------------------

@_skip
class TestImageWorkflow(unittest.TestCase):
    """Full workflow: Upload → Thumbnail → Analyze → Workspace persistence."""

    def setUp(self):
        self.client = _get_client()

    def _upload(self, data: bytes, name: str) -> str:
        r = self.client.post("/api/images/upload", files=[_img_file(data, name)])
        self.assertEqual(r.status_code, 200)
        return r.json()["images"][0]["id"]

    def test_full_workflow(self):
        """Upload, verify thumbnail, analyze, check workspace persistence."""
        # 1. Upload
        img_id = self._upload(_JPEG, "workflow.jpg")

        # 2. Verify thumbnail works
        r = self.client.get(f"/api/images/{img_id}/data")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/jpeg")

        # 3. Analyze
        r = self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["analyzed"], 1)
        result = r.json()["results"][0]["result"]
        self.assertIn("description", result)

        # 4. Verify workspace has the analysis result
        from kwb.api.deps import get_workspace
        ws = get_workspace()
        self.assertEqual(len(ws.image_analyses), 1)
        ia = ws.image_analyses[0]
        self.assertEqual(ia.image_id, img_id)
        self.assertTrue(ia.analyzed)
        self.assertIn("description", ia.result)
        self.assertTrue(ia.hash_sha256)
        self.assertGreater(ia.size_bytes, 0)

        # 5. List should show analyzed=True
        r = self.client.get("/api/images")
        img = next(i for i in r.json()["images"] if i["id"] == img_id)
        self.assertTrue(img["analyzed"])

    def test_workspace_serialization_with_images(self):
        """Image analyses survive workspace save/load cycle."""
        from kwb.core.workspace import Workspace, ImageAnalysisResult

        ws = Workspace(name="img-test")
        ws.save_image_analysis(ImageAnalysisResult(
            image_id="img_0001_test",
            filename="test.jpg",
            media_type="image/jpeg",
            size_bytes=1234,
            width=640,
            height=480,
            hash_sha256="abc123",
            exif_subset={"Model": "TestCam"},
            analyzed=True,
            result={"description": "Ein Testbild"},
            model="mock-model",
            analyzed_at="2026-01-01T00:00:00",
        ))

        # Roundtrip
        json_str = ws.to_json()
        ws2 = Workspace.from_json(json_str)
        self.assertEqual(len(ws2.image_analyses), 1)
        ia = ws2.image_analyses[0]
        self.assertEqual(ia.image_id, "img_0001_test")
        self.assertTrue(ia.analyzed)
        self.assertEqual(ia.result["description"], "Ein Testbild")
        self.assertEqual(ia.width, 640)
        self.assertEqual(ia.hash_sha256, "abc123")

    def test_clear_removes_from_disk(self):
        """DELETE /api/images also removes files from disk."""
        img_id = self._upload(_JPEG, "delete_me.jpg")

        # Verify file exists
        r = self.client.get(f"/api/images/{img_id}/data")
        self.assertEqual(r.status_code, 200)

        # Clear
        r = self.client.delete("/api/images")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["cleared"], 1)

        # File should be gone
        r = self.client.get(f"/api/images/{img_id}/data")
        self.assertEqual(r.status_code, 404)

    def test_analyze_auto_saves_workspace_to_disk(self):
        """ARCH-03: After analysis, workspace JSON is written to disk automatically."""
        import json
        from kwb.api.deps import get_workspace, workspace_dir, safe_filename

        img_id = self._upload(_JPEG, "persist_test.jpg")
        r = self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["analyzed"], 1)

        ws = get_workspace()
        ws_path = workspace_dir() / safe_filename(ws.name)
        self.assertTrue(ws_path.exists(), f"Workspace-Datei fehlt: {ws_path}")

        data = json.loads(ws_path.read_text(encoding="utf-8"))
        analyses = data.get("image_analyses", [])
        self.assertGreater(len(analyses), 0, "Keine image_analyses in der gespeicherten Datei")
        ids = [a["image_id"] for a in analyses]
        self.assertIn(img_id, ids)


@_skip
class TestImageDeleteSingle(unittest.TestCase):
    """DELETE /api/images/{img_id} — remove a single image (file + index + workspace)."""

    def setUp(self):
        self.client = _get_client()

    def _upload(self, data: bytes, name: str) -> str:
        r = self.client.post("/api/images/upload", files=[_img_file(data, name)])
        return r.json()["images"][0]["id"]

    def test_delete_removes_from_index_and_disk(self):
        from kwb.api.routes import ai as ai_routes
        img_id = self._upload(_JPEG, "to_delete.jpg")
        path = Path(ai_routes._uploaded_images[img_id]["path"])
        self.assertTrue(path.exists())
        r = self.client.delete(f"/api/images/{img_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["deleted"], img_id)
        self.assertNotIn(img_id, ai_routes._uploaded_images)
        self.assertFalse(path.exists())

    def test_delete_unknown_id_returns_404(self):
        r = self.client.delete("/api/images/img_9999_nope")
        self.assertEqual(r.status_code, 404)

    def test_delete_other_images_untouched(self):
        keep = self._upload(_JPEG, "keep.jpg")
        drop = self._upload(_PNG, "drop.png")
        self.client.delete(f"/api/images/{drop}")
        r = self.client.get("/api/images")
        ids = [i["id"] for i in r.json()["images"]]
        self.assertIn(keep, ids)
        self.assertNotIn(drop, ids)

    def test_delete_clears_workspace_entry(self):
        from kwb.api.deps import get_workspace
        img_id = self._upload(_JPEG, "with_analysis.jpg")
        self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        ws = get_workspace()
        self.assertIsNotNone(ws.get_image_analysis(img_id))
        self.client.delete(f"/api/images/{img_id}")
        self.assertIsNone(ws.get_image_analysis(img_id))


@_skip
class TestImageThumb(unittest.TestCase):
    """GET /api/images/{img_id}/thumb — server-rendered preview."""

    def setUp(self):
        self.client = _get_client()

    def _upload(self, data: bytes, name: str) -> str:
        r = self.client.post("/api/images/upload", files=[_img_file(data, name)])
        return r.json()["images"][0]["id"]

    def test_thumb_jpeg_falls_back_to_raw_without_pillow(self):
        """Without Pillow, JPEG/PNG/WebP serve the raw bytes as fallback."""
        from kwb.api.routes import ai as ai_routes
        if ai_routes._HAS_PIL:
            self.skipTest("Pillow installed — fallback path not exercised")
        img_id = self._upload(_JPEG, "foto.jpg")
        r = self.client.get(f"/api/images/{img_id}/thumb")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/jpeg")

    def test_thumb_tiff_returns_415_without_pillow(self):
        """TIFF cannot be rendered without Pillow — must return a clear error code."""
        from kwb.api.routes import ai as ai_routes
        if ai_routes._HAS_PIL:
            self.skipTest("Pillow installed — fallback path not exercised")
        img_id = self._upload(_TIFF, "scan.tif")
        r = self.client.get(f"/api/images/{img_id}/thumb")
        self.assertEqual(r.status_code, 415)

    def test_thumb_unknown_id_returns_404(self):
        r = self.client.get("/api/images/img_9999_nope/thumb")
        self.assertEqual(r.status_code, 404)


@_skip
class TestImageConfig(unittest.TestCase):
    """GET / POST /api/images/config — read and change the upload directory."""

    def setUp(self):
        self.client = _get_client()
        # Snapshot module-level state so we can restore after each test.
        from kwb.api.routes import ai as ai_routes
        self._original_dir = ai_routes._IMAGE_DIR
        self._original_from_env = ai_routes._IMAGE_DIR_FROM_ENV
        # Stub .env persistence so tests don't mutate the repo's .env file.
        from unittest.mock import patch
        self._patch = patch(
            "kwb.core.config.KWBConfig.save_to_dotenv",
            lambda *a, **kw: None,
        )
        self._patch.start()

    def tearDown(self):
        from kwb.api.routes import ai as ai_routes
        ai_routes._IMAGE_DIR = self._original_dir
        ai_routes._IMAGE_DIR_FROM_ENV = self._original_from_env
        self._patch.stop()

    def test_config_reports_upload_dir(self):
        r = self.client.get("/api/images/config")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIn("upload_dir", d)
        self.assertTrue(d["upload_dir"])
        self.assertIn("configured_via_env", d)
        self.assertEqual(d["env_var"], "KWB_IMAGE_DIR")
        self.assertIn("thumbnails_supported", d)
        self.assertIsInstance(d["thumbnails_supported"], bool)

    def test_post_config_changes_upload_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            r = self.client.post("/api/images/config", json={"upload_dir": td})
            self.assertEqual(r.status_code, 200, r.text)
            d = r.json()
            self.assertEqual(Path(d["upload_dir"]).resolve(), Path(td).resolve())
            self.assertTrue(d["configured_via_env"])

            # Subsequent uploads must land in the new directory.
            up = self.client.post(
                "/api/images/upload",
                files=[_img_file(_JPEG, "after_switch.jpg")],
            )
            self.assertEqual(up.status_code, 200)
            from kwb.api.routes import ai as ai_routes
            new_img_path = Path(
                ai_routes._uploaded_images[up.json()["images"][0]["id"]]["path"]
            )
            self.assertEqual(new_img_path.parent.resolve(), Path(td).resolve())

    def test_post_config_creates_missing_directory(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "nested" / "scans"
            self.assertFalse(target.exists())
            r = self.client.post("/api/images/config", json={"upload_dir": str(target)})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(target.exists())

    def test_post_config_empty_resets_to_default(self):
        r = self.client.post("/api/images/config", json={"upload_dir": ""})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertFalse(d["configured_via_env"])
        # Default sits inside the system temp dir.
        import tempfile as _t
        self.assertTrue(d["upload_dir"].startswith(_t.gettempdir()))


if __name__ == "__main__":
    unittest.main()
