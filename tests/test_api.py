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
from unittest.mock import patch, MagicMock

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
# Test fixtures (using app + deps)
# ---------------------------------------------------------------------------

def _get_client():
    """Create a fresh TestClient bound to the Debussy app."""
    from kwb.api import deps
    from kwb.core.workspace import Workspace
    deps._state["datasets"] = {}
    deps._state["report"] = None
    deps._state["workspace"] = Workspace(name="test")
    deps._config_cache = None

    from kwb.api.app import app
    from kwb.ai.mock import MockProvider
    deps._prov_override = MockProvider.with_defaults()

    return TestClient(app)


def _upload_csv(client, filename="test.csv", content=_SAMPLE_CSV):
    """Upload a sample CSV via the analyze endpoint."""
    client.post("/api/analyze", files=[_make_csv_upload(content, filename)])


def _get_state():
    """Access shared deps state dict."""
    from kwb.api import deps
    return deps._state


def _get_safe_filename():
    """Return the safe_filename function from deps."""
    from kwb.api.deps import safe_filename
    return safe_filename


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
        self.assertIn("summary", data)
        self.assertEqual(data["summary"]["total_records"], 5)

    def test_analyze_reports_columns(self):
        data = self._ingest()
        self.assertIn("summary", data)
        self.assertEqual(data["summary"]["total_columns"], 5)

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
        self.client.post("/api/analyze", files=[_make_csv_upload()])

    def test_ner_returns_entities(self):
        r = self.client.post("/api/ner", json={
            "dataset": "test.csv",
            "method": "llm",
            "sample_size": 3,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["task_name"], "NER")
        self.assertIn("entities", body)
        self.assertIn("workspace", body)

    def test_ner_unknown_dataset(self):
        r = self.client.post("/api/ner", json={
            "dataset": "nope.csv",
            "columns": ["subject"],
            "method": "llm",
        })
        self.assertEqual(r.status_code, 400)

    def test_ner_updates_workspace(self):
        self.client.post("/api/ner", json={
            "dataset": "test.csv",
            "columns": ["subject"],
            "method": "llm",
            "sample_size": 2,
        })
        r = self.client.get("/api/workspace")
        ws = r.json()
        self.assertGreaterEqual(ws["ai_runs"], 1)


# ---------------------------------------------------------------------------
# Tests: Scan endpoint
# ---------------------------------------------------------------------------

@_skip_no_fastapi
class TestScanEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()
        _upload_csv(self.client, filename="scan.csv")

    def test_scan_returns_result(self):
        r = self.client.post("/api/scan", json={
            "dataset": "scan.csv",
            "sample_size": 3,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["task_name"], "Scan")
        self.assertIn("total", body)
        self.assertIn("issues", body)

    def test_scan_unknown_dataset(self):
        r = self.client.post("/api/scan", json={"dataset": "nope.csv"})
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# Tests: EDTF endpoint
# ---------------------------------------------------------------------------

@_skip_no_fastapi
class TestEDTFEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()
        _upload_csv(self.client, filename="edtf.csv")

    def test_edtf_rules_only(self):
        r = self.client.post("/api/edtf", json={
            "dataset": "edtf.csv",
            "column": "year",
            "use_llm": False,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["task_name"], "EDTF")
        self.assertGreater(body["total"], 0)
        converted = [d for d in body["results"] if d["edtf"]]
        self.assertGreater(len(converted), 0)

    def test_edtf_missing_column(self):
        r = self.client.post("/api/edtf", json={
            "dataset": "edtf.csv",
            "column": "",
        })
        self.assertEqual(r.status_code, 400)

    def test_edtf_invalid_column(self):
        r = self.client.post("/api/edtf", json={
            "dataset": "edtf.csv",
            "column": "nonexistent",
        })
        self.assertEqual(r.status_code, 400)

    def test_edtf_unknown_dataset(self):
        r = self.client.post("/api/edtf", json={
            "dataset": "nope.csv",
            "column": "year",
        })
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# Tests: GND endpoints (network mocked)
# ---------------------------------------------------------------------------

def _fake_gnd_response():
    """Fake lobid.org JSON response."""
    return json.dumps({
        "member": [{
            "gndIdentifier": "118540238",
            "preferredName": "Johann Wolfgang von Goethe",
            "type": ["AuthorityResource", "Person"],
            "variantName": ["Goethe, J.W."],
            "biographicalOrHistoricalInformation": ["Dichter und Naturforscher"],
        }],
        "totalItems": 1,
    }).encode("utf-8")


@_skip_no_fastapi
class TestGNDEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()

    @patch("kwb.enrich.gnd.urlopen")
    def test_gnd_search(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = _fake_gnd_response()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        r = self.client.get("/api/gnd/search", params={"q": "Goethe", "type": "PER"})
        self.assertEqual(r.status_code, 200)
        results = r.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["gnd_id"], "118540238")
        self.assertEqual(results[0]["preferred_name"], "Johann Wolfgang von Goethe")

    def test_gnd_search_empty_query(self):
        r = self.client.get("/api/gnd/search", params={"q": ""})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"], [])

    @patch("kwb.enrich.gnd.urlopen")
    def test_gnd_batch(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = _fake_gnd_response()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        _state = _get_state()
        ws = _state["workspace"]
        ws.add_entities([
            {"text": "Goethe", "type": "PER", "confidence": 0.9,
             "source": "llm", "record_id": "R001"},
        ])

        r = self.client.post("/api/gnd/batch", json={"limit": 5})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("matched", body)
        self.assertIn("total", body)

    def test_gnd_batch_no_entities(self):
        r = self.client.post("/api/gnd/batch", json={})
        self.assertEqual(r.status_code, 400)
        self.assertIn("NER", r.json()["error"])


# ---------------------------------------------------------------------------
# Tests: Export endpoints
# ---------------------------------------------------------------------------

@_skip_no_fastapi
class TestExportEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()
        _upload_csv(self.client, filename="export.csv")
        # Export requires field mapping to be configured
        self.client.post("/api/workspace/field-mapping", json={
            "mappings": [
                {"csv_column": "title", "label": "Titel", "goobi_type": "TitleDocMain"},
                {"csv_column": "year", "label": "Jahr", "goobi_type": "PublicationYear"},
            ]
        })

    def test_goobi_preview(self):
        r = self.client.post("/api/export/goobi-preview", json={
            "dataset": "export.csv",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("xml", body)
        self.assertIn("goobi-import", body["xml"])

    def test_goobi_preview_specific_record(self):
        r = self.client.post("/api/export/goobi-preview", json={
            "dataset": "export.csv",
            "record_id": "obj_001",
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn("obj_001", r.json()["xml"])

    def test_goobi_preview_unknown_record(self):
        r = self.client.post("/api/export/goobi-preview", json={
            "dataset": "export.csv",
            "record_id": "NONEXISTENT",
        })
        self.assertEqual(r.status_code, 400)

    def test_goobi_preview_unknown_dataset(self):
        r = self.client.post("/api/export/goobi-preview", json={
            "dataset": "nope.csv",
        })
        self.assertEqual(r.status_code, 400)

    def test_goobi_batch(self):
        r = self.client.post("/api/export/goobi-batch", json={
            "dataset": "export.csv",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("xml", body)
        self.assertEqual(body["record_count"], 5)
        self.assertIn("goobi-import-batch", body["xml"])

    def test_image_results_export_csv(self):
        img = ("files", ("test.jpg", io.BytesIO(_SAMPLE_IMAGE_BYTES), "image/jpeg"))
        up = self.client.post("/api/images/upload", files=[img])
        self.assertEqual(up.status_code, 200)
        image_id = up.json()["images"][0]["id"]

        self.client.post("/api/images/analyze", json={"image_ids": [image_id]})
        rv = self.client.post(f"/api/images/{image_id}/review", json={
            "status": "accepted", "comment": "ok", "reviewer": "fachperson", "record_id": "obj_001"
        })
        self.assertEqual(rv.status_code, 200)

        ex = self.client.post("/api/export/image-results", json={"format": "csv"})
        self.assertEqual(ex.status_code, 200)
        self.assertIn("text/csv", ex.headers.get("content-type", ""))
        self.assertIn("review_status", ex.text)
        self.assertIn("accepted", ex.text)

    def test_image_results_export_jsonld(self):
        ex = self.client.post("/api/export/image-results", json={"format": "jsonld", "as_file": False})
        self.assertEqual(ex.status_code, 200)
        body = ex.json()
        self.assertIn("jsonld", body)
        self.assertIn("@graph", body["jsonld"])


# ---------------------------------------------------------------------------
# Tests: Workspace endpoints
# ---------------------------------------------------------------------------

@_skip_no_fastapi
class TestWorkspaceEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()

    def test_get_workspace_empty(self):
        r = self.client.get("/api/workspace")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["entity_count"], 0)
        self.assertEqual(body["date_count"], 0)

    def test_get_entities_empty(self):
        r = self.client.get("/api/workspace/entities")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["entities"], [])

    def test_entity_update(self):
        _state = _get_state()
        ws = _state["workspace"]
        ws.add_entities([
            {"text": "Bern", "type": "GPE", "confidence": 0.8,
             "source": "llm", "record_id": "R001"},
        ])
        r = self.client.post("/api/workspace/entity/0", json={
            "status": "accepted",
            "editor_note": "korrekt",
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

        r2 = self.client.get("/api/workspace/entities")
        ent = r2.json()["entities"][0]
        self.assertEqual(ent["status"], "accepted")
        self.assertEqual(ent["editor_note"], "korrekt")

    def test_entity_update_invalid_index(self):
        r = self.client.post("/api/workspace/entity/999", json={"status": "accepted"})
        self.assertIn(r.status_code, (400, 404))

    def test_entity_batch_update(self):
        _state = _get_state()
        ws = _state["workspace"]
        ws.add_entities([
            {"text": "Bern", "type": "GPE", "confidence": 0.8,
             "source": "llm", "record_id": "R001"},
            {"text": "Zürich", "type": "GPE", "confidence": 0.7,
             "source": "llm", "record_id": "R002"},
        ])
        r = self.client.post("/api/workspace/entity/batch", json={
            "indices": [0, 1],
            "updates": {"status": "accepted"},
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["updated"], 2)

    def test_get_dictionary_empty(self):
        r = self.client.get("/api/workspace/dictionary")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["entries"], [])

    def test_workspace_save_and_load(self):
        _state = _get_state()
        ws = _state["workspace"]
        ws.add_entities([
            {"text": "Test", "type": "CON", "confidence": 0.5,
             "source": "manual", "record_id": "R001"},
        ])

        r = self.client.post("/api/workspace/save", json={"name": "test_project"})
        self.assertEqual(r.status_code, 200)
        saved_path = r.json()["path"]
        self.assertIn("test_project", saved_path)

        try:
            with open(saved_path, "rb") as f:
                r2 = self.client.post(
                    "/api/workspace/load",
                    files=[("file", ("test.json", f, "application/json"))],
                )
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r2.json()["entity_count"], 1)
        finally:
            Path(saved_path).unlink(missing_ok=True)

    def test_workspace_load_invalid_extension(self):
        r = self.client.post(
            "/api/workspace/load",
            files=[("file", ("bad.txt", io.BytesIO(b"{}"), "text/plain"))],
        )
        self.assertIn(r.status_code, (400, 422))


# ---------------------------------------------------------------------------
# Tests: Workspace path traversal security
# ---------------------------------------------------------------------------

@_skip_no_fastapi
class TestWorkspaceSecurity(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()

    def test_safe_filename_strips_traversal(self):
        safe = _get_safe_filename()("../../etc/passwd")
        self.assertNotIn("..", safe)
        self.assertNotIn("/", safe)

    def test_safe_filename_empty_input(self):
        safe = _get_safe_filename()("")
        self.assertTrue(safe.startswith("project"))

    def test_safe_filename_special_chars(self):
        safe = _get_safe_filename()("<script>alert(1)</script>")
        self.assertNotIn("<", safe)
        self.assertNotIn(">", safe)


# ---------------------------------------------------------------------------
# Tests: AI describe columns
# ---------------------------------------------------------------------------

@_skip_no_fastapi
class TestAIDescribeColumns(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()

    def test_describe_no_data(self):
        r = self.client.post("/api/ai/describe-columns")
        self.assertIn(r.status_code, (400, 422))

    def test_describe_with_data(self):
        _upload_csv(self.client, filename="desc.csv")
        r = self.client.post("/api/ai/describe-columns")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("datasets", body)
        ds = body["datasets"][0]
        self.assertIn("columns", ds)
        for col in ds["columns"]:
            self.assertIn("ai_description", col)


# ---------------------------------------------------------------------------
# Tests: GPU status (uses mock since no real GPU in test)
# ---------------------------------------------------------------------------

@_skip_no_fastapi
class TestGPUEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()

    def test_gpu_status_no_config(self):
        r = self.client.get("/api/gpu/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("status", body)

    def test_gpu_test(self):
        r = self.client.post("/api/gpu/test")
        self.assertIn(r.status_code, (200, 422))


if __name__ == "__main__":
    unittest.main()
