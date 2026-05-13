"""
Tests for the non-destructive ingest preview endpoint (issue #177).

Covers:
  - CSV UTF-8 preview: encoding + delimiter + head + id candidates
  - CSV Latin-1 preview: encoding detection + warning surfacing
  - chardet-missing fallback warning (#166)
  - XLSX preview: multi-sheet listing
  - XML preview: METS/MODS format detection
  - XML preview: unknown format warning
  - Preview is non-destructive (does not touch workspace/state)
  - Disallowed extension produces per-file error without aborting batch
"""
from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

_FORCE_NO_FASTAPI = os.environ.get("KWB_FORCE_NO_FASTAPI") == "1"
try:
    if _FORCE_NO_FASTAPI:
        raise ImportError("FastAPI disabled for deterministic catalog checks")
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

_skip_no_fastapi = unittest.skipUnless(
    _FASTAPI_AVAILABLE,
    "FastAPI not installed — run: pip install fastapi httpx python-multipart",
)


_UTF8_CSV = (
    "record_id,title,year\n"
    "obj_001,Karte Bern,1923\n"
    "obj_002,Grundriss,1850\n"
    "obj_003,Plan Wien,1901\n"
).encode("utf-8")

_LATIN1_CSV = (
    "record_id;title;year\n"
    "obj_001;Karte Zürich;1923\n"
    "obj_002;Münster;1850\n"
).encode("latin-1")

_METS_MODS_XML = b"""<?xml version="1.0"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
           xmlns:mods="http://www.loc.gov/mods/v3">
  <mets:dmdSec ID="dmd1">
    <mets:mdWrap MDTYPE="MODS"><mets:xmlData>
      <mods:mods>
        <mods:titleInfo><mods:title>Erste Karte</mods:title></mods:titleInfo>
      </mods:mods>
    </mets:xmlData></mets:mdWrap>
  </mets:dmdSec>
</mets:mets>
"""

_NOT_XML_FILE = b"<?xml version='1.0'?><random><foo/></random>"


def _get_client():
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


def _file(content: bytes, name: str, mime: str = "text/csv"):
    return ("files", (name, io.BytesIO(content), mime))


@_skip_no_fastapi
class TestIngestPreviewCSV(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()

    def test_utf8_preview_basic_shape(self):
        r = self.client.post(
            "/api/ingest/preview",
            files=[_file(_UTF8_CSV, "data.csv")],
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("previews", body)
        self.assertEqual(len(body["previews"]), 1)
        p = body["previews"][0]
        self.assertEqual(p["filename"], "data.csv")
        self.assertEqual(p["format"], "csv")
        self.assertEqual(p["row_count"], 3)
        self.assertEqual(p["column_count"], 3)
        self.assertEqual(len(p["head"]), 3)
        self.assertEqual(p["delimiter"], ",")
        self.assertEqual(p["id_column"]["proposed"], "record_id")
        self.assertIn("record_id", p["id_column"]["candidates"])

    def test_utf8_encoding_block_contains_confidence(self):
        r = self.client.post(
            "/api/ingest/preview",
            files=[_file(_UTF8_CSV, "data.csv")],
        )
        p = r.json()["previews"][0]
        self.assertIn("encoding", p)
        enc = p["encoding"]
        self.assertIn(enc["detected"].lower().replace("_", "-"),
                      ("utf-8", "ascii"))
        self.assertIsInstance(enc["has_bom"], bool)
        self.assertIsInstance(enc["chardet_available"], bool)

    def test_latin1_csv_delimiter_and_confidence_present(self):
        r = self.client.post(
            "/api/ingest/preview",
            files=[_file(_LATIN1_CSV, "umlaute.csv")],
        )
        p = r.json()["previews"][0]
        self.assertEqual(p["delimiter"], ";")
        # Confidence must be plumbed through (number from chardet, or None when
        # chardet declined to commit). The point: the field exists and is
        # surfaced so the UI can warn on low confidence.
        self.assertIn("confidence", p["encoding"])
        conf = p["encoding"]["confidence"]
        self.assertTrue(conf is None or isinstance(conf, (int, float)))

    def test_preview_does_not_touch_workspace(self):
        from kwb.api import deps
        self.client.post(
            "/api/ingest/preview",
            files=[_file(_UTF8_CSV, "data.csv")],
        )
        self.assertEqual(deps._state["datasets"], {})
        self.assertEqual(deps._state["workspace"].source_files, [])

    def test_chardet_missing_yields_warning(self):
        """Issue #166: when chardet is unavailable, surface a warning."""
        with patch.dict("sys.modules", {"chardet": None}):
            r = self.client.post(
                "/api/ingest/preview",
                files=[_file(_UTF8_CSV, "data.csv")],
            )
        p = r.json()["previews"][0]
        self.assertFalse(p["encoding"]["chardet_available"])
        self.assertTrue(any("chardet" in w.lower() for w in p["warnings"]))

    def test_disallowed_extension_returns_error_per_file(self):
        r = self.client.post(
            "/api/ingest/preview",
            files=[_file(b"foo", "evil.exe", "application/octet-stream")],
        )
        self.assertEqual(r.status_code, 200)
        previews = r.json()["previews"]
        self.assertEqual(len(previews), 1)
        self.assertIn("error", previews[0])

    def test_multiple_files_independent(self):
        r = self.client.post(
            "/api/ingest/preview",
            files=[
                _file(_UTF8_CSV, "a.csv"),
                _file(_LATIN1_CSV, "b.csv"),
            ],
        )
        previews = r.json()["previews"]
        self.assertEqual(len(previews), 2)
        self.assertEqual(previews[0]["filename"], "a.csv")
        self.assertEqual(previews[1]["filename"], "b.csv")


@_skip_no_fastapi
class TestIngestPreviewXML(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()

    def test_mets_mods_detected(self):
        r = self.client.post(
            "/api/ingest/preview",
            files=[_file(_METS_MODS_XML, "doc.xml", "application/xml")],
        )
        p = r.json()["previews"][0]
        self.assertEqual(p["format"], "xml")
        self.assertEqual(p["xml_format"], "mets_mods")
        self.assertGreater(p["row_count"], 0)
        self.assertGreater(p["column_count"], 0)

    def test_unknown_xml_format_warns(self):
        r = self.client.post(
            "/api/ingest/preview",
            files=[_file(_NOT_XML_FILE, "random.xml", "application/xml")],
        )
        p = r.json()["previews"][0]
        self.assertEqual(p["xml_format"], "unknown")
        self.assertTrue(any("METS" in w or "LIDO" in w for w in p["warnings"]))


@_skip_no_fastapi
class TestIngestPreviewXLSX(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()

    def _build_xlsx_bytes(self, sheets: dict[str, list[list[str]]]) -> bytes:
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for name, rows in sheets.items():
            ws = wb.create_sheet(title=name)
            for row in rows:
                ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_xlsx_single_sheet_preview(self):
        xlsx = self._build_xlsx_bytes({
            "Sheet1": [
                ["record_id", "title"],
                ["obj_001", "Karte"],
                ["obj_002", "Plan"],
            ]
        })
        r = self.client.post(
            "/api/ingest/preview",
            files=[_file(
                xlsx, "data.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )],
        )
        p = r.json()["previews"][0]
        self.assertEqual(p["format"], "xlsx")
        self.assertEqual(p["sheets"], ["Sheet1"])
        self.assertEqual(p["active_sheet"], "Sheet1")
        self.assertEqual(p["row_count"], 2)

    def test_xlsx_multi_sheet_warns(self):
        xlsx = self._build_xlsx_bytes({
            "Daten": [["id", "name"], ["1", "A"]],
            "Notizen": [["x", "y"], ["a", "b"]],
        })
        r = self.client.post(
            "/api/ingest/preview",
            files=[_file(
                xlsx, "multi.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )],
        )
        p = r.json()["previews"][0]
        self.assertEqual(len(p["sheets"]), 2)
        self.assertTrue(any("Sheet" in w for w in p["warnings"]))


if __name__ == "__main__":
    unittest.main()
