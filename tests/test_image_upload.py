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
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
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

    from kwb.api.app_new import app
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


if __name__ == "__main__":
    unittest.main()
