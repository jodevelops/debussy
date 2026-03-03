"""
API endpoint tests for Debussy v0.5.

Tests all FastAPI endpoints using starlette TestClient.
No external network calls — GND is mocked, AI uses MockProvider (automatic
fallback when no GPUStack configured).
"""
from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
from fastapi.testclient import TestClient

from kwb.api.app import app, _state, _safe_filename
from kwb.core.workspace import Workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv_bytes(rows: int = 5, with_id: bool = True) -> bytes:
    """Create a small synthetic CSV for upload."""
    data = {
        "record_id": [f"R{i:03d}" for i in range(1, rows + 1)],
        "title": [f"Objekt {i}" for i in range(1, rows + 1)],
        "date": ["1920", "ca. 1935", "1950-1960", "undatiert", "2001"][:rows],
        "subject": [
            "Minarett; Stadtmauer",
            "Fotografie; Landschaft",
            "Architektur",
            "Porträt; Person",
            "Karte",
        ][:rows],
    }
    if not with_id:
        del data["record_id"]
    df = pd.DataFrame(data)
    return df.to_csv(index=False).encode("utf-8")


def _upload_csv(client: TestClient, csv_bytes: bytes | None = None,
                filename: str = "test.csv") -> dict:
    """Upload a CSV and return the JSON response."""
    if csv_bytes is None:
        csv_bytes = _make_csv_bytes()
    resp = client.post(
        "/api/analyze",
        files=[("files", (filename, io.BytesIO(csv_bytes), "text/csv"))],
    )
    return resp


def _reset_state():
    """Reset app-level state between tests."""
    _state["datasets"] = {}
    _state["report"] = None
    _state["config"] = None
    _state["workspace"] = Workspace(name="test")


# ---------------------------------------------------------------------------
# Tests: Dashboard
# ---------------------------------------------------------------------------

class TestDashboard(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _reset_state()

    def test_get_dashboard_returns_html(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])

    def test_dashboard_contains_presets(self):
        r = self.client.get("/")
        self.assertIn("Debussy", r.text)


# ---------------------------------------------------------------------------
# Tests: Analyze
# ---------------------------------------------------------------------------

class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _reset_state()

    def test_upload_single_csv(self):
        r = _upload_csv(self.client)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("summary", body)
        self.assertIn("datasets", body)
        self.assertIn("findings", body)
        self.assertIn("markdown", body)
        self.assertEqual(len(body["datasets"]), 1)

    def test_upload_returns_dataset_profile(self):
        r = _upload_csv(self.client)
        ds = r.json()["datasets"][0]
        self.assertEqual(ds["row_count"], 5)
        self.assertEqual(ds["column_count"], 4)
        self.assertIn("columns", ds)

    def test_upload_no_files_returns_error(self):
        r = self.client.post("/api/analyze")
        self.assertIn(r.status_code, (400, 422))

    def test_upload_too_many_files(self):
        csv = _make_csv_bytes(2)
        files = [("files", (f"f{i}.csv", io.BytesIO(csv), "text/csv")) for i in range(11)]
        r = self.client.post("/api/analyze", files=files)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Maximal", r.json()["error"])

    def test_upload_invalid_extension(self):
        r = self.client.post(
            "/api/analyze",
            files=[("files", ("bad.xlsx", io.BytesIO(b"data"), "application/octet-stream"))],
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("erlaubt", r.json()["error"])

    def test_upload_two_csvs(self):
        csv1 = _make_csv_bytes(3)
        csv2 = _make_csv_bytes(2)
        r = self.client.post("/api/analyze", files=[
            ("files", ("a.csv", io.BytesIO(csv1), "text/csv")),
            ("files", ("b.csv", io.BytesIO(csv2), "text/csv")),
        ])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["datasets"]), 2)


# ---------------------------------------------------------------------------
# Tests: Dataset endpoints
# ---------------------------------------------------------------------------

class TestDatasetEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _reset_state()
        _upload_csv(self.client, filename="demo.csv")

    def test_get_columns(self):
        r = self.client.get("/api/dataset/demo.csv/columns")
        self.assertEqual(r.status_code, 200)
        cols = r.json()["columns"]
        names = [c["name"] for c in cols]
        self.assertIn("title", names)
        self.assertIn("record_id", names)

    def test_get_columns_unknown_dataset(self):
        r = self.client.get("/api/dataset/nope.csv/columns")
        self.assertEqual(r.status_code, 404)

    def test_get_records(self):
        r = self.client.get("/api/dataset/demo.csv/records")
        self.assertEqual(r.status_code, 200)
        ids = r.json()["record_ids"]
        self.assertEqual(len(ids), 5)
        self.assertIn("R001", ids)

    def test_get_records_unknown(self):
        r = self.client.get("/api/dataset/nope.csv/records")
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# Tests: NER endpoint
# ---------------------------------------------------------------------------

class TestNEREndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _reset_state()
        _upload_csv(self.client, filename="ner.csv")

    def test_ner_llm_method(self):
        r = self.client.post("/api/ner", json={
            "dataset": "ner.csv",
            "columns": ["subject"],
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
            "dataset": "ner.csv",
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

class TestScanEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _reset_state()
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

class TestEDTFEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _reset_state()
        _upload_csv(self.client, filename="edtf.csv")

    def test_edtf_rules_only(self):
        r = self.client.post("/api/edtf", json={
            "dataset": "edtf.csv",
            "column": "date",
            "use_llm": False,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["task_name"], "EDTF")
        self.assertGreater(body["total"], 0)
        # "1920" should be converted by rules
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
            "column": "date",
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


class TestGNDEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _reset_state()

    @patch("kwb.enrich.gnd.urllib.request.urlopen")
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

    @patch("kwb.enrich.gnd.urllib.request.urlopen")
    def test_gnd_batch(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = _fake_gnd_response()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        # Need entities in workspace first
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

class TestExportEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _reset_state()
        _upload_csv(self.client, filename="export.csv")

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
            "record_id": "R001",
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn("R001", r.json()["xml"])

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


# ---------------------------------------------------------------------------
# Tests: Workspace endpoints
# ---------------------------------------------------------------------------

class TestWorkspaceEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _reset_state()

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

        # Verify update persisted
        r2 = self.client.get("/api/workspace/entities")
        ent = r2.json()["entities"][0]
        self.assertEqual(ent["status"], "accepted")
        self.assertEqual(ent["editor_note"], "korrekt")

    def test_entity_update_invalid_index(self):
        r = self.client.post("/api/workspace/entity/999", json={"status": "accepted"})
        self.assertEqual(r.status_code, 400)

    def test_entity_batch_update(self):
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
        ws = _state["workspace"]
        ws.add_entities([
            {"text": "Test", "type": "CON", "confidence": 0.5,
             "source": "manual", "record_id": "R001"},
        ])

        # Save
        r = self.client.post("/api/workspace/save", json={"name": "test_project"})
        self.assertEqual(r.status_code, 200)
        saved_path = r.json()["path"]
        self.assertIn("test_project", saved_path)

        try:
            # Load it back
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
        self.assertEqual(r.status_code, 400)
        self.assertIn("json", r.json()["error"].lower())


# ---------------------------------------------------------------------------
# Tests: Workspace path traversal security
# ---------------------------------------------------------------------------

class TestWorkspaceSecurity(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _reset_state()

    def test_safe_filename_strips_traversal(self):
        safe = _safe_filename("../../etc/passwd")
        self.assertNotIn("..", safe)
        self.assertNotIn("/", safe)

    def test_safe_filename_empty_input(self):
        safe = _safe_filename("")
        self.assertTrue(safe.startswith("project"))

    def test_safe_filename_special_chars(self):
        safe = _safe_filename("<script>alert(1)</script>")
        self.assertNotIn("<", safe)
        self.assertNotIn(">", safe)


# ---------------------------------------------------------------------------
# Tests: AI describe columns
# ---------------------------------------------------------------------------

class TestAIDescribeColumns(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _reset_state()

    def test_describe_no_data(self):
        r = self.client.post("/api/ai/describe-columns")
        self.assertEqual(r.status_code, 400)

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

class TestGPUEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _reset_state()

    def test_gpu_status_no_config(self):
        r = self.client.get("/api/gpu/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["available"])

    def test_gpu_test(self):
        r = self.client.post("/api/gpu/test")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # MockProvider returns ok
        self.assertIn("ok", body)


if __name__ == "__main__":
    unittest.main()
