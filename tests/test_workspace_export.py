"""Tests for Workspace, GND, and Goobi Export."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from kwb.core.workspace import Workspace, ImageAnalysisResult, ImageReviewStatus
from kwb.export.goobi_xml import export_goobi_xml, export_goobi_batch


class TestWorkspaceBasic(unittest.TestCase):
    def test_create_empty(self):
        ws = Workspace(name="test")
        self.assertEqual(ws.name, "test")
        self.assertEqual(len(ws.entities), 0)
        self.assertEqual(len(ws.dates), 0)

    def test_add_entities(self):
        ws = Workspace()
        ws.add_entities([
            {"text": "Bern", "type": "GPE", "confidence": 0.9, "source": "llm", "record_id": "r1"},
            {"text": "Müller", "type": "PER", "confidence": 0.8, "source": "spacy", "record_id": "r1"},
        ])
        self.assertEqual(len(ws.entities), 2)
        self.assertEqual(ws.entities[0].text, "Bern")
        self.assertEqual(ws.entities[0].status, "pending")

    def test_update_entity(self):
        ws = Workspace()
        ws.add_entities([{"text": "Bern", "type": "GPE"}])
        ws.update_entity(0, {"status": "accepted", "gnd_id": "4005762-8"})
        self.assertEqual(ws.entities[0].status, "accepted")
        self.assertEqual(ws.entities[0].gnd_id, "4005762-8")

    def test_entities_by_status(self):
        ws = Workspace()
        ws.add_entities([{"text": "A", "type": "PER"}, {"text": "B", "type": "LOC"}])
        ws.update_entity(0, {"status": "accepted"})
        st = ws.entities_by_status()
        self.assertEqual(st["accepted"], 1)
        self.assertEqual(st["pending"], 1)

    def test_unique_entities(self):
        ws = Workspace()
        ws.add_entities([
            {"text": "Bern", "type": "GPE", "confidence": 0.6, "source": "spacy"},
            {"text": "Bern", "type": "GPE", "confidence": 0.95, "source": "llm"},
        ])
        unique = ws.unique_entities()
        self.assertEqual(len(unique), 1)
        self.assertAlmostEqual(unique[0].confidence, 0.95)

    def test_add_dates(self):
        ws = Workspace()
        ws.add_dates([
            {"original": "ca. 1920", "edtf": "1920~", "confidence": 0.95, "method": "rule", "record_id": "r1"},
        ])
        self.assertEqual(len(ws.dates), 1)
        self.assertEqual(ws.dates[0].edtf, "1920~")

    def test_dictionary(self):
        ws = Workspace()
        ws.add_to_dictionary([
            {"term": "Bern", "gnd_id": "4005762-8", "category": "GPE", "source": "gnd-api"},
            {"term": "Bern", "gnd_id": "dup"},  # duplicate — should be skipped
        ])
        self.assertEqual(len(ws.dictionary), 1)
        self.assertEqual(ws.dictionary[0].gnd_id, "4005762-8")

    def test_log_ai_run(self):
        ws = Workspace()
        ws.log_ai_run("ner_extract", "gpt-oss-120b", total=10, succeeded=9, duration=5.5)
        self.assertEqual(len(ws.ai_runs), 1)
        self.assertEqual(ws.ai_runs[0]["task"], "ner_extract")


class TestWorkspacePersistence(unittest.TestCase):
    def test_save_load_roundtrip(self):
        ws = Workspace(name="test-project")
        ws.source_files = ["data.csv"]
        ws.add_entities([
            {"text": "ETH Zürich", "type": "ORG", "confidence": 0.9, "gnd_id": "36150-1"},
        ])
        ws.add_dates([{"original": "1920er", "edtf": "192X", "confidence": 0.95, "method": "rule"}])
        ws.add_to_dictionary([{"term": "ETH Zürich", "gnd_id": "36150-1", "category": "ORG"}])
        ws.field_mapping = {"title": ("Titel", "TitleDocMain")}

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        ws.save(path)
        loaded = Workspace.load(path)

        self.assertEqual(loaded.name, "test-project")
        self.assertEqual(len(loaded.entities), 1)
        self.assertEqual(loaded.entities[0].text, "ETH Zürich")
        self.assertEqual(loaded.entities[0].gnd_id, "36150-1")
        self.assertEqual(len(loaded.dates), 1)
        self.assertEqual(loaded.dates[0].edtf, "192X")
        self.assertEqual(len(loaded.dictionary), 1)
        self.assertEqual(loaded.field_mapping["title"], ["Titel", "TitleDocMain"])

        Path(path).unlink()

    def test_to_summary(self):
        ws = Workspace(name="test")
        ws.add_entities([{"text": "A", "type": "PER"}, {"text": "B", "type": "LOC"}])
        ws.update_entity(0, {"status": "accepted"})
        s = ws.to_summary()
        self.assertEqual(s["entity_count"], 2)
        self.assertEqual(s["entity_status"]["accepted"], 1)


class TestGoobiExport(unittest.TestCase):
    def test_basic_export(self):
        df = pd.DataFrame({
            "record_id": ["obj_1", "obj_2"],
            "title": ["Ansicht Bern", "Matterhorn Panorama"],
            "date": ["1923", "ca. 1900"],
        })
        ws = Workspace()
        ws.field_mapping = {
            "title": ("Titel", "TitleDocMain"),
            "date": ("Erscheinungsjahr", "PublicationYear"),
        }
        results = export_goobi_xml(df, ws)
        self.assertEqual(len(results), 2)
        rid, xml = results[0]
        self.assertEqual(rid, "obj_1")
        self.assertIn("CatalogIDDigital", xml)
        self.assertIn("obj_1", xml)
        self.assertIn("Ansicht Bern", xml)

    def test_export_with_entities(self):
        df = pd.DataFrame({"record_id": ["obj_1"], "title": ["Test"]})
        ws = Workspace()
        ws.field_mapping = {"title": ("Titel", "TitleDocMain")}
        ws.add_entities([
            {"text": "Peter Müller", "type": "PER", "record_id": "obj_1",
             "gnd_id": "123456", "source": "llm"},
            {"text": "Universität Bern", "type": "ORG", "record_id": "obj_1",
             "gnd_id": "36154-9", "source": "llm"},
            {"text": "Bern", "type": "GPE", "record_id": "obj_1",
             "gnd_id": "4005762-8", "source": "llm"},
        ])
        results = export_goobi_xml(df, ws)
        xml = results[0][1]
        self.assertIn("<person", xml)
        self.assertIn('lastname="Müller"', xml)
        self.assertIn('valueURI="123456"', xml)
        self.assertIn("<corporate", xml)
        self.assertIn('name="Universität Bern"', xml)
        self.assertIn("SubjectTopic", xml)  # GPE as subject
        self.assertIn("4005762-8", xml)

    def test_rejected_entities_excluded(self):
        df = pd.DataFrame({"record_id": ["obj_1"], "title": ["Test"]})
        ws = Workspace()
        ws.field_mapping = {"title": ("Titel", "TitleDocMain")}
        ws.add_entities([{"text": "Wrong", "type": "PER", "record_id": "obj_1"}])
        ws.update_entity(0, {"status": "rejected"})
        results = export_goobi_xml(df, ws)
        xml = results[0][1]
        self.assertNotIn("Wrong", xml)

    def test_edtf_date_override(self):
        df = pd.DataFrame({"record_id": ["obj_1"], "date": ["ungefähr 1920"]})
        ws = Workspace()
        ws.field_mapping = {"date": ("Erscheinungsjahr", "PublicationYear")}
        ws.add_dates([{"original": "ungefähr 1920", "edtf": "1920~",
                       "confidence": 0.95, "record_id": "obj_1"}])
        results = export_goobi_xml(df, ws)
        xml = results[0][1]
        self.assertIn("1920~", xml)

    def test_batch_export(self):
        df = pd.DataFrame({"record_id": ["r1", "r2"], "title": ["A", "B"]})
        ws = Workspace()
        ws.field_mapping = {"title": ("Titel", "TitleDocMain")}
        batch_xml = export_goobi_batch(df, ws)
        self.assertIn("goobi-import-batch", batch_xml)
        self.assertIn("r1", batch_xml)
        self.assertIn("r2", batch_xml)

    def test_collection_multival(self):
        df = pd.DataFrame({"record_id": ["obj_1"], "coll": ["Physik; Architektur; Kunst"]})
        ws = Workspace()
        ws.field_mapping = {"coll": ("Sammlung", "singleDigCollection")}
        results = export_goobi_xml(df, ws)
        xml = results[0][1]
        self.assertEqual(xml.count("singleDigCollection"), 3)

    def test_accepted_image_mapping_flows_into_goobi(self):
        df = pd.DataFrame({"record_id": ["obj_1"], "title": ["Test"]})
        ws = Workspace()
        ws.field_mapping = {
            "title": ("Titel", "TitleDocMain"),
            "image.description": ("Bildbeschreibung", "Description"),
            "image.objects": ("Bildobjekte", "SubjectTopic"),
        }
        ws.save_image_analysis(ImageAnalysisResult(
            image_id="img_1",
            filename="test.jpg",
            analyzed=True,
            result={"description": "Architekturansicht", "objects": ["Kirche", "Turm"]},
            record_id="obj_1",
            review_status=ImageReviewStatus.ACCEPTED,
        ))
        xml = export_goobi_xml(df, ws)[0][1]
        self.assertIn("Architekturansicht", xml)
        self.assertIn("Kirche", xml)


# GND tests are network-dependent, so we test the module structure only
class TestGNDModule(unittest.TestCase):
    def test_imports(self):
        from kwb.enrich.gnd import GNDResult
        r = GNDResult(gnd_id="123", preferred_name="Test")
        self.assertEqual(r.uri, "https://d-nb.info/gnd/123")
        d = r.to_dict()
        self.assertEqual(d["gnd_id"], "123")

    def test_type_filter(self):
        from kwb.enrich.gnd import GND_TYPE_FILTER
        self.assertEqual(GND_TYPE_FILTER["PER"], "Person")
        self.assertEqual(GND_TYPE_FILTER["ORG"], "CorporateBody")
        self.assertEqual(GND_TYPE_FILTER["LOC"], "PlaceOrGeographicName")


if __name__ == "__main__":
    unittest.main()


# ========================================
# P0 Security Tests (no FastAPI dependency)
# ========================================

class TestSecurityP0(unittest.TestCase):
    """Tests for Sprint 1 security fixes."""

    def test_safe_filename_logic(self):
        """P0-3: _safe_filename sanitization logic."""
        import re
        def _safe_filename(name, ext=".debussy.json"):
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())[:80]
            safe = re.sub(r"\.{2,}", ".", safe)
            safe = safe.strip("._- ")
            return (safe or "project") + ext

        # Normal names
        self.assertEqual(_safe_filename("my_project"), "my_project.debussy.json")
        self.assertEqual(_safe_filename("test-123"), "test-123.debussy.json")

        # Path traversal
        r = _safe_filename("../../etc/passwd")
        self.assertNotIn("..", r)
        self.assertNotIn("/", r)

        # XSS in name
        r = _safe_filename('<script>alert(1)</script>')
        self.assertNotIn("<", r)
        self.assertNotIn(">", r)

        # Empty
        self.assertEqual(_safe_filename(""), "project.debussy.json")
        self.assertEqual(_safe_filename("   "), "project.debussy.json")

        # Length limit
        r = _safe_filename("a" * 200)
        self.assertLess(len(r), 200)

    def test_localhost_default(self):
        """P0-2: Default binding is localhost."""
        code = Path("src/kwb/api/app.py").read_text()
        self.assertIn('"127.0.0.1"', code)
        self.assertIn("KWB_HOST", code)

    def test_upload_limits_in_code(self):
        """P0-4: Security limits are defined in deps.py."""
        code = Path("src/kwb/api/deps.py").read_text()
        for c in ["MAX_UPLOAD_FILES", "MAX_FILE_BYTES", "MAX_WORKSPACE_BYTES",
                   "MAX_CSV_ROWS", "MAX_CSV_COLS", "ALLOWED_EXTENSIONS"]:
            self.assertIn(c, code, f"Missing: {c}")

    def test_upload_validation_in_analyze(self):
        """P0-4: analyze route validates uploads."""
        code = Path("src/kwb/api/routes/analyze.py").read_text()
        self.assertIn("MAX_UPLOAD_FILES", code)
        self.assertIn("ALLOWED_EXTENSIONS", code)
        self.assertIn("MAX_FILE_BYTES", code)
        self.assertIn("MAX_CSV_ROWS", code)

    def test_workspace_save_uses_safe_filename(self):
        """P0-3: workspace save uses sanitized filename."""
        code = Path("src/kwb/api/routes/workspace.py").read_text()
        self.assertIn("safe_filename", code)
        deps_code = Path("src/kwb/api/deps.py").read_text()
        self.assertIn("_WORKSPACE_DIR", deps_code)

    def test_xss_protection_in_html(self):
        """P0-1: JS has XSS protection (reads from modular parts/dashboard.js)."""
        import re
        script = Path("src/kwb/api/parts/dashboard.js").read_text()
        # No template literals with interpolation
        tpls = re.findall(r'`[^`]*\$\{[^}]*\}[^`]*`', script)
        self.assertEqual(len(tpls), 0, f"Unsafe template literals: {tpls[:3]}")
        # esc() used extensively
        self.assertGreaterEqual(script.count('esc('), 40)
        # safeOpt used for options
        self.assertIn('safeOpt(', script)


    def test_dashboard_js_core_actions_are_not_corrupted(self):
        """Regression: NER/Scan/EDTF actions stay valid and use per-tab prompts."""
        # JS was extracted to parts/dashboard.js during modularization
        js = Path("src/kwb/api/parts/dashboard.js").read_text()
        self.assertIn("async function runNER", js)
        self.assertIn("async function runScan", js)
        self.assertIn("async function runEDTF", js)

        # per-tab prompts are wired with null-safe fallback to global cfg prompt
        self.assertIn("$('ner-sp')", js)
        self.assertIn("$('scan-sp')", js)
        self.assertIn("$('cfg-sys').value", js)

        # broken duplicate fragments must not exist
        self.assertNotIn("system_prompt:$('cfg-sys').value})})).json();\n    if(r.error)throw Error(r.error);nerData", js)
        self.assertNotIn("system_prompt:$('cfg-sys').value})})).json();\n    if(r.error)throw Error(r.error);renderScan", js)
        self.assertNotIn("system_prompt:$('cfg-sys').value})})).json();\n    if(r.error)throw Error(r.error);edtfData", js)
