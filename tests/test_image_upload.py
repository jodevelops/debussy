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


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Thumb endpoint tests (/api/images/{id}/thumb)
# ---------------------------------------------------------------------------

@_skip
class TestImageThumb(unittest.TestCase):
    """GET /api/images/{img_id}/thumb — browser-renderable thumbnail for all formats."""

    def setUp(self):
        self.client = _get_client()

    def _upload(self, data: bytes, name: str) -> str:
        r = self.client.post("/api/images/upload", files=[_img_file(data, name)])
        self.assertEqual(r.status_code, 200)
        return r.json()["images"][0]["id"]

    def test_thumb_jpeg_returns_jpeg(self):
        """JPEG /thumb serves original JPEG bytes."""
        img_id = self._upload(_JPEG, "foto.jpg")
        r = self.client.get(f"/api/images/{img_id}/thumb")
        self.assertEqual(r.status_code, 200)
        self.assertIn("image/jpeg", r.headers["content-type"])
        self.assertEqual(r.content, _JPEG)

    def test_thumb_png_returns_png(self):
        """PNG /thumb serves original PNG bytes."""
        img_id = self._upload(_PNG, "zeichnung.png")
        r = self.client.get(f"/api/images/{img_id}/thumb")
        self.assertEqual(r.status_code, 200)
        self.assertIn("image/png", r.headers["content-type"])

    def test_thumb_webp_returns_webp(self):
        """WebP /thumb serves original bytes."""
        img_id = self._upload(_WEBP, "thumb.webp")
        r = self.client.get(f"/api/images/{img_id}/thumb")
        self.assertEqual(r.status_code, 200)
        self.assertIn("image/webp", r.headers["content-type"])

    def test_thumb_tiff_no_embedded_returns_svg(self):
        """TIFF without embedded JPEG preview → SVG placeholder (browser-renderable)."""
        img_id = self._upload(_TIFF, "archiv.tif")
        r = self.client.get(f"/api/images/{img_id}/thumb")
        self.assertEqual(r.status_code, 200)
        ct = r.headers["content-type"]
        # Must be either image/svg+xml (no embedded preview) or image/jpeg (if preview found)
        self.assertTrue(
            "image/svg+xml" in ct or "image/jpeg" in ct,
            f"Expected SVG or JPEG for TIFF thumb, got: {ct}"
        )
        if "image/svg+xml" in ct:
            # SVG must be valid XML starting with <svg
            self.assertIn(b"<svg", r.content)
            self.assertIn(b"TIFF", r.content)

    def test_thumb_tiff_long_ext_returns_svg_or_jpeg(self):
        """TIFF with .tiff extension also gets SVG/JPEG thumb."""
        img_id = self._upload(_TIFF, "scan.tiff")
        r = self.client.get(f"/api/images/{img_id}/thumb")
        self.assertEqual(r.status_code, 200)
        ct = r.headers["content-type"]
        self.assertTrue("image/svg+xml" in ct or "image/jpeg" in ct)

    def test_thumb_unknown_id_returns_404(self):
        """Unknown img_id → 404."""
        r = self.client.get("/api/images/img_9999_ghost/thumb")
        self.assertEqual(r.status_code, 404)

    def test_thumb_tiff_with_embedded_jpeg_returns_jpeg(self):
        """
        TIFF containing an embedded JPEG thumbnail (tags 513/514) → serve as JPEG.

        We construct a minimal TIFF with a fake embedded JPEG in IFD.
        """
        import struct

        # Build minimal little-endian TIFF with one IFD entry pointing to JPEG
        jpeg_data = _JPEG
        jpeg_offset = 8 + 2 + 12 * 2 + 4  # header + num_entries + 2 entries + next_ifd

        tiff = bytearray()
        tiff += b"II"                          # byte order: little-endian
        tiff += struct.pack("<H", 42)           # TIFF magic
        tiff += struct.pack("<I", 8)            # IFD offset = 8

        # IFD: 2 entries
        tiff += struct.pack("<H", 2)            # num_entries

        # Tag 513 = JPEGInterchangeFormat (type=LONG, count=1, value=offset)
        tiff += struct.pack("<HHII", 513, 4, 1, jpeg_offset)
        # Tag 514 = JPEGInterchangeFormatLength (type=LONG, count=1, value=length)
        tiff += struct.pack("<HHII", 514, 4, 1, len(jpeg_data))
        # Next IFD offset = 0 (no more IFDs)
        tiff += struct.pack("<I", 0)
        # Append the actual JPEG data
        tiff += jpeg_data

        img_id = self._upload(bytes(tiff), "with_preview.tif")
        r = self.client.get(f"/api/images/{img_id}/thumb")
        self.assertEqual(r.status_code, 200)
        ct = r.headers["content-type"]
        self.assertIn("image/jpeg", ct, f"Expected JPEG for TIFF with embedded preview, got: {ct}")
        self.assertEqual(r.content, jpeg_data)


# ---------------------------------------------------------------------------
# Vision analysis result fields (MockProvider)
# ---------------------------------------------------------------------------

@_skip
class TestVisionAnalysisFields(unittest.TestCase):
    """Verify that vision analysis returns all 16 GLAM fields."""

    def setUp(self):
        self.client = _get_client()

    def _upload_and_analyze(self, data=_JPEG, name="test.jpg") -> dict:
        r = self.client.post("/api/images/upload", files=[_img_file(data, name)])
        img_id = r.json()["images"][0]["id"]
        r2 = self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        results = r2.json()["results"]
        return results[0]["result"] if results and "result" in results[0] else {}

    def test_result_has_description(self):
        r = self._upload_and_analyze()
        self.assertIn("description", r)
        self.assertIsInstance(r["description"], str)
        self.assertGreater(len(r["description"]), 5)

    def test_result_has_color_mode(self):
        r = self._upload_and_analyze()
        self.assertIn("color_mode", r)
        self.assertIn(r["color_mode"], ("bw", "color", "sepia", "colorized"))

    def test_result_has_persons_fields(self):
        r = self._upload_and_analyze()
        self.assertIn("has_persons", r)
        self.assertIn("person_count", r)
        self.assertIsInstance(r["has_persons"], bool)
        self.assertIsInstance(r["person_count"], int)

    def test_result_has_text_fields(self):
        r = self._upload_and_analyze()
        self.assertIn("has_text", r)
        self.assertIn("text_readable", r)
        self.assertIn("text_type", r)

    def test_result_has_medium(self):
        r = self._upload_and_analyze()
        self.assertIn("medium", r)

    def test_result_has_condition(self):
        r = self._upload_and_analyze()
        self.assertIn("condition", r)

    def test_result_has_orientation(self):
        r = self._upload_and_analyze()
        self.assertIn("orientation", r)

    def test_result_has_iconography(self):
        r = self._upload_and_analyze()
        self.assertIn("iconography", r)
        self.assertIsInstance(r["iconography"], list)

    def test_result_has_confidence(self):
        r = self._upload_and_analyze()
        self.assertIn("confidence", r)
        self.assertIsInstance(r["confidence"], (int, float))

    def test_result_has_estimated_date_range(self):
        r = self._upload_and_analyze()
        self.assertIn("estimated_date_range", r)

    def test_tiff_also_analyzed(self):
        """TIFF files are also sent to vision model for analysis."""
        r = self._upload_and_analyze(_TIFF, "archiv.tif")
        self.assertIn("description", r)

    def test_mock_provider_vision_fields_complete(self):
        """MockProvider.with_defaults() returns all 16 GLAM analysis fields."""
        from kwb.ai.mock import MockProvider
        from kwb.ai.provider import AIMessage
        import json

        mock = MockProvider.with_defaults()
        msgs = [
            AIMessage.system("test"),
            AIMessage.user([
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
                {"type": "text", "text": "Analysiere"},
            ]),
        ]
        resp = mock.complete(msgs)
        data = json.loads(resp.content)
        for field in [
            "description", "objects", "persons", "has_persons", "person_count",
            "has_text", "text_type", "text_readable", "transcription_hint",
            "color_mode", "material", "medium", "condition", "iconography",
            "orientation", "estimated_date_range", "confidence",
        ]:
            self.assertIn(field, data, f"Missing field: {field}")
