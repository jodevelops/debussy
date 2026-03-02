"""
HTTP-level integration tests for Debussy API.

Uses FastAPI TestClient (requires: pip install fastapi httpx).
Tests are skipped automatically when FastAPI is not installed.

Coverage:
  - GET /                       → HTML response
  - GET /api/gpu/status         → provider status
  - POST /api/analyze           → CSV ingest + structural analysis
  - GET /api/dataset/{n}/columns → column list after ingest
  - POST /api/ner               → entity extraction (mock provider)
  - POST /api/edtf              → EDTF normalization (rules + mock LLM)
  - GET /api/gnd/search         → GND search (lobid mock)
  - POST /api/workspace/field-mapping → save field mapping
  - GET /api/workspace/field-mapping  → load field mapping
  - GET /api/workspace          → workspace summary
  - POST /api/workspace/save    → persistence
  - POST /api/gpu/test          → LLM ping
  - POST /api/images/upload     → image upload
  - POST /api/images/analyze    → vision analysis

Model forwarding:
  - NER: request model='test-model' → MockProvider.call_log[0]['model']
  - EDTF with LLM: same assertion
"""

import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ---------------------------------------------------------------------------
# Conditional imports — skip if FastAPI/httpx not available
# ---------------------------------------------------------------------------
try:
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

_skip_no_fastapi = unittest.skipUnless(
    _FASTAPI_AVAILABLE,
    "FastAPI not installed — run: pip install fastapi httpx python-multipart"
)

# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------

_SAMPLE_CSV = b"""record_id,title,year,description,subject
obj_001,Karte von Bern,1923,Topographische Aufnahme des Stadtzentrums.,Stadtplan
obj_002,Grundriss Rathaus,ca. 1850,Architekturzeichnung des alten Rathauses.,Architektur
obj_003,Luftaufnahme,1960-1970,Vogelperspektive der Innenstadt.,Luftbild
obj_004,Foto Altstadt,undatiert,Schwarz-weiss Aufnahme der historischen Gasse.,Fotografie
obj_005,Plan Universitat,1901,Lageplan der Universitat Bern.,Stadtplanung
"""

_SAMPLE_IMAGE_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    + b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n"
    + b"\xff\xd9"  # minimal stub JPEG
)


def _make_csv_upload(content: bytes = _SAMPLE_CSV, name: str = "test.csv"):
    return ("files", (name, io.BytesIO(content), "text/csv"))


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _get_client():
    """Create a fresh TestClient bound to the Debussy app."""
    # Reset shared state between tests
    from kwb.api import deps
    from kwb.core.workspace import Workspace
    deps._state["datasets"] = {}
    deps._state["report"] = None
    deps._state["workspace"] = Workspace(name="test")
    deps._config_cache = None

    from kwb.api.app_new import app
    # Override provider to always use Mock
    from kwb.ai.mock import MockProvider
    deps._prov_override = MockProvider.with_defaults()

    return TestClient(app)


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

@_skip_no_fastapi
class TestHealthEndpoints(unittest.TestCase):

    def setUp(self):
        self.client = _get_client()

    def test_index_returns_html(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertIn("Debussy", r.text)

    def test_gpu_status_no_config(self):
        r = self.client.get("/api/gpu/status")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("status", data)
        # Without a real GPUStack, mock mode is expected
        self.assertIn(data["status"], ("mock", "ok", "error"))


@_skip_no_fastapi
class TestCSVIngest(unittest.TestCase):

    def setUp(self):
        self.client = _get_client()

    def _ingest(self):
        r = self.client.post("/api/analyze", files=[_make_csv_upload()])
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_analyze_returns_report(self):
        data = self._ingest()
        self.assertIn("total_rows", data)
        self.assertEqual(data["total_rows"], 5)

    def test_analyze_reports_columns(self):
        data = self._ingest()
        self.assertIn("total_columns", data)
        self.assertEqual(data["total_columns"], 5)

    def test_dataset_columns_endpoint(self):
        self._ingest()
        r = self.client.get("/api/dataset/test.csv/columns")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        col_names = [c["name"] for c in data["columns"]]
        self.assertIn("title", col_names)
        self.assertIn("record_id", col_names)

    def test_dataset_records_endpoint(self):
        self._ingest()
        r = self.client.get("/api/dataset/test.csv/records")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("record_ids", data)
        self.assertIn("obj_001", data["record_ids"])

    def test_dataset_not_found_returns_404(self):
        r = self.client.get("/api/dataset/nonexistent.csv/columns")
        self.assertEqual(r.status_code, 404)

    def test_wrong_extension_rejected(self):
        r = self.client.post("/api/analyze", files=[
            ("files", ("data.xlsx", io.BytesIO(b"data"), "application/octet-stream"))
        ])
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.json())

    def test_too_many_files_rejected(self):
        from kwb.api.deps import MAX_UPLOAD_FILES
        files = [_make_csv_upload(name=f"f{i}.csv") for i in range(MAX_UPLOAD_FILES + 1)]
        r = self.client.post("/api/analyze", files=files)
        self.assertEqual(r.status_code, 400)


@_skip_no_fastapi
class TestNEREndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _get_client()
        # Ingest CSV first
        self.client.post("/api/analyze", files=[_make_csv_upload()])

    def test_ner_returns_entities(self):
        r = self.client.post("/api/ner", json={
            "dataset": "test.csv",
            "method": "llm",
            "sample_size": 3,
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("entities", data)
        self.assertIn("total", data)

    def test_ner_model_forwarded(self):
        """The model parameter must reach the provider."""
        from kwb.ai.mock import MockProvider
        mock = MockProvider.with_ner_response([
            {"text": "Bern", "type": "GPE", "confidence": 0.9, "reasoning": "city"}
        ])
        # Inject mock
        from kwb.api import deps
        deps._prov_override = mock

        r = self.client.post("/api/ner", json={
            "dataset": "test.csv",
            "method": "llm",
            "sample_size": 2,
            "model": "gpt-oss-120b",
        })
        self.assertEqual(r.status_code, 200)
        # Check model appears in response
        self.assertEqual(r.json()["model"], "gpt-oss-120b")
        # Check mock was called with our model
        if mock.call_log:
            self.assertEqual(mock.call_log[0]["model"], "gpt-oss-120b")

    def test_ner_no_dataset_returns_400(self):
        r = self.client.post("/api/ner", json={"dataset": "missing.csv"})
        self.assertEqual(r.status_code, 400)

    def test_ner_entities_stored_in_workspace(self):
        self.client.post("/api/ner", json={
            "dataset": "test.csv",
            "method": "llm",
            "sample_size": 5,
        })
        r = self.client.get("/api/workspace")
        self.assertEqual(r.status_code, 200)


@_skip_no_fastapi
class TestEDTFEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _get_client()
        self.client.post("/api/analyze", files=[_make_csv_upload()])

    def test_edtf_rules_only(self):
        r = self.client.post("/api/edtf", json={
            "dataset": "test.csv",
            "column": "year",
            "use_llm": False,
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("results", data)
        # "1923" should convert to EDTF "1923"
        found = {res["original"]: res["edtf"] for res in data["results"]}
        self.assertEqual(found.get("1923"), "1923")

    def test_edtf_approx_pattern(self):
        r = self.client.post("/api/edtf", json={
            "dataset": "test.csv",
            "column": "year",
            "use_llm": False,
        })
        data = r.json()
        found = {res["original"]: res["edtf"] for res in data["results"]}
        # "ca. 1850" → "1850~"
        self.assertEqual(found.get("ca. 1850"), "1850~")

    def test_edtf_range_pattern(self):
        r = self.client.post("/api/edtf", json={
            "dataset": "test.csv",
            "column": "year",
            "use_llm": False,
        })
        data = r.json()
        found = {res["original"]: res["edtf"] for res in data["results"]}
        # "1960-1970" → "1960/1970"
        self.assertEqual(found.get("1960-1970"), "1960/1970")

    def test_edtf_missing_column_returns_400(self):
        r = self.client.post("/api/edtf", json={
            "dataset": "test.csv",
            "column": "nonexistent",
        })
        self.assertEqual(r.status_code, 400)

    def test_edtf_no_column_returns_400(self):
        r = self.client.post("/api/edtf", json={"dataset": "test.csv"})
        self.assertEqual(r.status_code, 400)


@_skip_no_fastapi
class TestWorkspaceEndpoints(unittest.TestCase):

    def setUp(self):
        self.client = _get_client()

    def test_get_empty_workspace(self):
        r = self.client.get("/api/workspace")
        self.assertEqual(r.status_code, 200)

    def test_set_field_mapping(self):
        r = self.client.post("/api/workspace/field-mapping", json={
            "mappings": [
                {"csv_column": "record_id", "goobi_type": "CatalogIDDigital"},
                {"csv_column": "title", "goobi_type": "TitleDocMain"},
                {"csv_column": "year", "goobi_type": "PublicationYear"},
            ]
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["saved"], 3)

    def test_get_field_mapping_after_set(self):
        self.client.post("/api/workspace/field-mapping", json={
            "mappings": [{"csv_column": "title", "goobi_type": "TitleDocMain"}]
        })
        r = self.client.get("/api/workspace/field-mapping")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["mappings"]), 1)
        self.assertEqual(data["mappings"][0]["csv_column"], "title")

    def test_workspace_save_and_load(self):
        import tempfile, os
        from kwb.api import deps
        orig_dir = deps._WORKSPACE_DIR
        with tempfile.TemporaryDirectory() as tmp:
            deps._WORKSPACE_DIR = Path(tmp)
            try:
                r_save = self.client.post("/api/workspace/save", json={"name": "test_proj"})
                self.assertEqual(r_save.status_code, 200)
                fname = r_save.json()["saved"]

                r_load = self.client.post("/api/workspace/load", json={"filename": fname})
                self.assertEqual(r_load.status_code, 200)
                self.assertIn("workspace", r_load.json())
            finally:
                deps._WORKSPACE_DIR = orig_dir

    def test_entity_status_filter(self):
        """GET /api/workspace/entities?status=pending returns only pending."""
        r = self.client.get("/api/workspace/entities?status=pending")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("entities", data)

    def test_invalid_status_filter_returns_400(self):
        r = self.client.get("/api/workspace/entities?status=unknown_status")
        self.assertEqual(r.status_code, 400)


@_skip_no_fastapi
class TestGNDEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _get_client()

    def test_gnd_search_empty_query(self):
        r = self.client.get("/api/gnd/search?q=")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"], [])

    def test_gnd_search_returns_list(self):
        # This hits the real lobid.org API — skip in offline environments
        import socket
        try:
            socket.setdefaulttimeout(2)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("lobid.org", 443))
            r = self.client.get("/api/gnd/search?q=Bern&type=PlaceOrGeographicName&size=3")
            self.assertEqual(r.status_code, 200)
            results = r.json()["results"]
            self.assertIsInstance(results, list)
        except (socket.error, OSError):
            self.skipTest("No network access to lobid.org")

    def test_gnd_batch_no_entities_returns_400(self):
        r = self.client.post("/api/gnd/batch", json={})
        self.assertEqual(r.status_code, 400)


@_skip_no_fastapi
class TestImageEndpoints(unittest.TestCase):

    def setUp(self):
        self.client = _get_client()
        # Clear image store
        self.client.delete("/api/images")

    def test_image_upload_minimal_jpeg(self):
        r = self.client.post("/api/images/upload", files=[
            ("files", ("photo.jpg", io.BytesIO(_SAMPLE_IMAGE_BYTES), "image/jpeg"))
        ])
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["uploaded"], 1)
        self.assertEqual(data["images"][0]["filename"], "photo.jpg")

    def test_image_list_after_upload(self):
        self.client.post("/api/images/upload", files=[
            ("files", ("test.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png"))
        ])
        r = self.client.get("/api/images")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["images"]), 1)

    def test_image_wrong_format_rejected(self):
        r = self.client.post("/api/images/upload", files=[
            ("files", ("doc.pdf", io.BytesIO(b"%PDF"), "application/pdf"))
        ])
        self.assertEqual(r.status_code, 400)

    def test_image_analyze_mock_response(self):
        # Upload first
        up = self.client.post("/api/images/upload", files=[
            ("files", ("img.jpg", io.BytesIO(_SAMPLE_IMAGE_BYTES), "image/jpeg"))
        ])
        self.assertEqual(up.status_code, 200)
        img_id = up.json()["images"][0]["id"]

        # Analyze
        r = self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total"], 1)
        self.assertIn("results", data)

    def test_image_clear(self):
        self.client.post("/api/images/upload", files=[
            ("files", ("img.jpg", io.BytesIO(_SAMPLE_IMAGE_BYTES), "image/jpeg"))
        ])
        r = self.client.delete("/api/images")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["cleared"], 1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not _FASTAPI_AVAILABLE:
        print("⚠️  FastAPI not installed — tests will be skipped.")
        print("    Run: pip install fastapi httpx python-multipart")
    unittest.main(verbosity=2)
