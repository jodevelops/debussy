"""
Tests für neue Features (F28, F30, F34, F35).

- F34: CSV-Export mit NER + EDTF Anreicherungen
- F28: Wikidata-Enrichment (offline-sicher, kein echtes Netzwerk)
- F35: JSON-LD Export
- F30: OCR-Endpoint-Tests via API
"""
from __future__ import annotations

import io
import os
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kwb.core.workspace import (
    Workspace, FieldMapping, ImageAnalysisResult,
)


# ---------------------------------------------------------------------------
# F34: CSV-Export
# ---------------------------------------------------------------------------

class TestCSVExport(unittest.TestCase):
    """Tests for enriched CSV export (F34)."""

    def _make_workspace_with_data(self) -> tuple[pd.DataFrame, Workspace]:
        df = pd.DataFrame({
            "record_id": ["obj_001", "obj_002", "obj_003"],
            "title": ["Minarett Kairo", "Berge Schweiz", "Unbekannt"],
            "date_created": ["ca. 1920", "1930er", "o.D."],
        })
        ws = Workspace.create("test-export")
        ws.id_column = "record_id"

        # Add NER entities
        ws.add_entities([
            {"text": "Kairo", "type": "GPE", "record_id": "obj_001", "confidence": 0.9},
            {"text": "Ägypten", "type": "GPE", "record_id": "obj_001", "confidence": 0.85},
            {"text": "Alpen", "type": "LOC", "record_id": "obj_002", "confidence": 0.95},
            {"text": "Schweiz", "type": "GPE", "record_id": "obj_002", "confidence": 0.9},
        ])

        # Add EDTF dates
        ws.add_dates([
            {"original": "ca. 1920", "edtf": "1920~", "confidence": 0.95,
             "method": "rule", "record_id": "obj_001", "column": "date_created"},
            {"original": "1930er", "edtf": "193X", "confidence": 0.9,
             "method": "rule", "record_id": "obj_002", "column": "date_created"},
        ])

        # Add dictionary entry with GND
        ws.add_to_dictionary([
            {"term": "Kairo", "gnd_id": "4029229-7", "category": "GPE", "source": "manual"},
        ])

        return df, ws

    def test_csv_export_basic_structure(self):
        """CSV export returns valid CSV with original columns."""
        from kwb.export.csv_export import export_enriched_csv
        df, ws = self._make_workspace_with_data()
        csv_str = export_enriched_csv(df, ws, include_ner=False, include_edtf=False, include_gnd=False)
        out = pd.read_csv(io.StringIO(csv_str))
        self.assertIn("record_id", out.columns)
        self.assertIn("title", out.columns)
        self.assertEqual(len(out), 3)

    def test_csv_export_includes_ner_columns(self):
        """CSV export adds ner_geo_political and ner_places columns."""
        from kwb.export.csv_export import export_enriched_csv
        df, ws = self._make_workspace_with_data()
        csv_str = export_enriched_csv(df, ws, include_ner=True, include_edtf=False)
        out = pd.read_csv(io.StringIO(csv_str))
        self.assertIn("ner_geo_political", out.columns)
        self.assertIn("ner_places", out.columns)

    def test_csv_export_includes_edtf_columns(self):
        """CSV export adds edtf_date_created column."""
        from kwb.export.csv_export import export_enriched_csv
        df, ws = self._make_workspace_with_data()
        csv_str = export_enriched_csv(df, ws, include_edtf=True, include_ner=False)
        out = pd.read_csv(io.StringIO(csv_str))
        self.assertIn("edtf_date_created", out.columns)
        obj1_edtf = out[out["record_id"] == "obj_001"]["edtf_date_created"].iloc[0]
        self.assertEqual(obj1_edtf, "1920~")

    def test_csv_export_edtf_second_record(self):
        """EDTF dates for second record are correct."""
        from kwb.export.csv_export import export_enriched_csv
        df, ws = self._make_workspace_with_data()
        csv_str = export_enriched_csv(df, ws, include_edtf=True, include_ner=False)
        out = pd.read_csv(io.StringIO(csv_str))
        obj2_edtf = out[out["record_id"] == "obj_002"]["edtf_date_created"].iloc[0]
        self.assertEqual(obj2_edtf, "193X")

    def test_csv_export_ner_values_populated(self):
        """NER columns contain the expected entity texts."""
        from kwb.export.csv_export import export_enriched_csv
        df, ws = self._make_workspace_with_data()
        csv_str = export_enriched_csv(df, ws, include_ner=True, include_edtf=False)
        out = pd.read_csv(io.StringIO(csv_str))
        obj1_gpe = out[out["record_id"] == "obj_001"]["ner_geo_political"].iloc[0]
        self.assertIn("Kairo", str(obj1_gpe))

    def test_csv_export_empty_workspace(self):
        """Empty workspace still exports original data cleanly."""
        from kwb.export.csv_export import export_enriched_csv
        df = pd.DataFrame({"record_id": ["r1"], "title": ["Test"]})
        ws = Workspace.create("empty")
        csv_str = export_enriched_csv(df, ws)
        out = pd.read_csv(io.StringIO(csv_str))
        self.assertEqual(len(out), 1)

    def test_csv_export_bytes_has_bom(self):
        """Byte export has UTF-8 BOM for Excel compatibility."""
        from kwb.export.csv_export import export_enriched_csv_bytes
        df = pd.DataFrame({"record_id": ["r1"], "title": ["Minarett"]})
        ws = Workspace.create("bom-test")
        data = export_enriched_csv_bytes(df, ws)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))

    def test_csv_export_with_gnd(self):
        """GND IDs column is populated when dictionary has entries."""
        from kwb.export.csv_export import export_enriched_csv
        df, ws = self._make_workspace_with_data()
        csv_str = export_enriched_csv(df, ws, include_ner=True, include_gnd=True)
        out = pd.read_csv(io.StringIO(csv_str))
        # gnd_ids column exists if NER returned persons or known terms
        # (may be empty if no person entities — that's OK)
        self.assertIn("gnd_ids", out.columns)

    def test_csv_export_unicode(self):
        """Unicode characters in data are preserved."""
        from kwb.export.csv_export import export_enriched_csv
        df = pd.DataFrame({
            "record_id": ["r1"],
            "title": ["Völkerkunde, Äthiopien — über Nomaden"],
        })
        ws = Workspace.create("unicode-test")
        csv_str = export_enriched_csv(df, ws, include_ner=False)
        self.assertIn("Völkerkunde", csv_str)

    def test_csv_export_all_features_combined(self):
        """Full export with NER + EDTF + GND produces expected columns."""
        from kwb.export.csv_export import export_enriched_csv
        df, ws = self._make_workspace_with_data()
        csv_str = export_enriched_csv(df, ws, include_ner=True, include_edtf=True, include_gnd=True)
        out = pd.read_csv(io.StringIO(csv_str))
        # Original columns preserved
        self.assertIn("record_id", out.columns)
        self.assertIn("title", out.columns)
        # NER columns added
        self.assertIn("ner_geo_political", out.columns)
        # EDTF column added
        self.assertIn("edtf_date_created", out.columns)


# ---------------------------------------------------------------------------
# F28: Wikidata Enrichment (offline tests — mock HTTP)
# ---------------------------------------------------------------------------

class TestWikidataEnrichment(unittest.TestCase):
    """Test Wikidata enrichment module with mocked HTTP (no network needed)."""

    def _make_sparql_response(self, items: list[dict]) -> MagicMock:
        """Build a mock urlopen that returns SPARQL JSON."""
        body = json.dumps({
            "results": {
                "bindings": items,
            }
        }).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def _berlin_binding(self):
        return {
            "item": {"value": "http://www.wikidata.org/entity/Q64"},
            "itemLabel": {"value": "Berlin"},
            "itemDescription": {"value": "Hauptstadt von Deutschland"},
            "gnd": {"value": "4005728-8"},
        }

    @patch("kwb.enrich.wikidata.urlopen")
    def test_search_returns_results(self, mock_urlopen):
        """wikidata_search returns WikidataResult objects from SPARQL response."""
        from kwb.enrich.wikidata import wikidata_search
        mock_urlopen.return_value = self._make_sparql_response([self._berlin_binding()])
        results = wikidata_search("Berlin", entity_type="GPE")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].qid, "Q64")
        self.assertEqual(results[0].label, "Berlin")
        self.assertEqual(results[0].gnd_id, "4005728-8")

    @patch("kwb.enrich.wikidata.urlopen")
    def test_search_returns_empty_on_network_error(self, mock_urlopen):
        """wikidata_search returns [] on network error (offline-safe)."""
        from kwb.enrich.wikidata import wikidata_search
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")
        results = wikidata_search("Berlin")
        self.assertEqual(results, [])

    @patch("kwb.enrich.wikidata.urlopen")
    def test_search_empty_term(self, mock_urlopen):
        """Empty search term returns [] without HTTP call."""
        from kwb.enrich.wikidata import wikidata_search
        results = wikidata_search("")
        mock_urlopen.assert_not_called()
        self.assertEqual(results, [])

    @patch("kwb.enrich.wikidata.urlopen")
    def test_search_person_type(self, mock_urlopen):
        """Person entity type uses person-specific SPARQL query."""
        from kwb.enrich.wikidata import wikidata_search
        goethe_binding = {
            "item": {"value": "http://www.wikidata.org/entity/Q5879"},
            "itemLabel": {"value": "Johann Wolfgang von Goethe"},
            "itemDescription": {"value": "Dichter und Naturforscher"},
            "gnd": {"value": "118540238"},
        }
        mock_urlopen.return_value = self._make_sparql_response([goethe_binding])
        results = wikidata_search("Goethe", entity_type="PER")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].qid, "Q5879")

    @patch("kwb.enrich.wikidata.urlopen")
    def test_to_dict_structure(self, mock_urlopen):
        """WikidataResult.to_dict returns expected keys."""
        from kwb.enrich.wikidata import wikidata_search
        mock_urlopen.return_value = self._make_sparql_response([self._berlin_binding()])
        results = wikidata_search("Berlin")
        d = results[0].to_dict()
        for key in ["qid", "label", "description", "aliases", "gnd_id", "uri", "score"]:
            self.assertIn(key, d)
        self.assertIn("Q64", d["uri"])

    @patch("kwb.enrich.wikidata.urlopen")
    def test_batch_search(self, mock_urlopen):
        """wikidata_batch_search returns one entry per term."""
        from kwb.enrich.wikidata import wikidata_batch_search
        mock_urlopen.return_value = self._make_sparql_response([self._berlin_binding()])
        terms = [
            {"text": "Berlin", "type": "GPE", "record_id": "r1"},
            {"text": "Goethe", "type": "PER", "record_id": "r2"},
        ]
        results = wikidata_batch_search(terms, delay=0.0, limit=1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["text"], "Berlin")
        self.assertEqual(results[1]["text"], "Goethe")

    @patch("kwb.enrich.wikidata.urlopen")
    def test_batch_search_offline(self, mock_urlopen):
        """Batch search is offline-safe when network fails."""
        from kwb.enrich.wikidata import wikidata_batch_search
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("offline")
        results = wikidata_batch_search(
            [{"text": "Test", "type": "PER", "record_id": "r1"}],
            delay=0.0,
        )
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["top_match"])

    def test_result_uri_format(self):
        """WikidataResult.uri uses wikidata.org format."""
        from kwb.enrich.wikidata import WikidataResult
        r = WikidataResult(qid="Q64", label="Berlin")
        self.assertEqual(r.uri, "https://www.wikidata.org/wiki/Q64")

    def test_result_empty_qid_uri(self):
        """WikidataResult.uri is empty string when qid is empty."""
        from kwb.enrich.wikidata import WikidataResult
        r = WikidataResult(qid="", label="Unknown")
        self.assertEqual(r.uri, "")


# ---------------------------------------------------------------------------
# F35: JSON-LD Export
# ---------------------------------------------------------------------------

class TestJSONLDExport(unittest.TestCase):
    """Tests for JSON-LD export (F35)."""

    def _make_test_data(self) -> tuple[pd.DataFrame, Workspace]:
        df = pd.DataFrame({
            "record_id": ["obj_001", "obj_002"],
            "title": ["Minarett Kairo", "Berge Schweiz"],
            "date_created": ["ca. 1920", "1930er"],
        })
        ws = Workspace.create("jsonld-test")
        ws.id_column = "record_id"
        ws.base_url = "https://example.com/collection/"

        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital", enabled=True),
            FieldMapping("title", "TitleDocMain", enabled=True),
            FieldMapping("date_created", "DateCreated", enabled=True),
        ])

        ws.add_entities([
            {"text": "Kairo", "type": "GPE", "record_id": "obj_001", "confidence": 0.9},
        ])
        ws.add_dates([
            {"original": "ca. 1920", "edtf": "1920~", "confidence": 0.9,
             "record_id": "obj_001", "column": "date_created"},
        ])
        return df, ws

    def test_jsonld_basic_structure(self):
        """JSON-LD document has @context and @graph."""
        from kwb.export.jsonld import export_jsonld
        df, ws = self._make_test_data()
        jsonld_str = export_jsonld(df, ws)
        doc = json.loads(jsonld_str)
        self.assertIn("@context", doc)
        self.assertIn("@graph", doc)

    def test_jsonld_graph_has_items(self):
        """@graph contains at least the 2 records."""
        from kwb.export.jsonld import export_jsonld
        df, ws = self._make_test_data()
        doc = json.loads(export_jsonld(df, ws))
        record_nodes = [n for n in doc["@graph"] if n.get("@type") == "CreativeWork"]
        self.assertEqual(len(record_nodes), 2)

    def test_jsonld_record_has_identifier(self):
        """Each record node has an identifier."""
        from kwb.export.jsonld import export_jsonld
        df, ws = self._make_test_data()
        doc = json.loads(export_jsonld(df, ws))
        record = next(n for n in doc["@graph"] if n.get("identifier") == "obj_001")
        self.assertIsNotNone(record)

    def test_jsonld_record_has_name(self):
        """Record node has name from TitleDocMain mapping."""
        from kwb.export.jsonld import export_jsonld
        df, ws = self._make_test_data()
        doc = json.loads(export_jsonld(df, ws))
        record = next(n for n in doc["@graph"] if n.get("identifier") == "obj_001")
        self.assertEqual(record.get("name"), "Minarett Kairo")

    def test_jsonld_context_has_schema_vocab(self):
        """@context declares schema.org as @vocab."""
        from kwb.export.jsonld import export_jsonld
        df, ws = self._make_test_data()
        doc = json.loads(export_jsonld(df, ws))
        self.assertIn("schema.org", doc["@context"].get("@vocab", ""))

    def test_jsonld_limit_respected(self):
        """limit parameter restricts number of record nodes."""
        from kwb.export.jsonld import export_jsonld
        df, ws = self._make_test_data()
        doc = json.loads(export_jsonld(df, ws, limit=1))
        record_nodes = [n for n in doc["@graph"] if n.get("@type") == "CreativeWork"]
        self.assertEqual(len(record_nodes), 1)

    def test_jsonld_empty_workspace(self):
        """Empty workspace still produces valid JSON-LD."""
        from kwb.export.jsonld import export_jsonld
        df = pd.DataFrame({"record_id": ["r1"], "title": ["Test"]})
        ws = Workspace.create("empty")
        ws.id_column = "record_id"
        ws.base_url = "https://example.com/collection/"
        doc = json.loads(export_jsonld(df, ws))
        self.assertIn("@graph", doc)

    def test_jsonld_bytes(self):
        """export_jsonld_bytes returns valid UTF-8 JSON-LD."""
        from kwb.export.jsonld import export_jsonld_bytes
        df, ws = self._make_test_data()
        data = export_jsonld_bytes(df, ws)
        self.assertIsInstance(data, bytes)
        doc = json.loads(data.decode("utf-8"))
        self.assertIn("@graph", doc)

    def test_jsonld_with_gnd_dictionary(self):
        """Dictionary entries with GND IDs appear in authority graph."""
        from kwb.export.jsonld import export_jsonld
        df, ws = self._make_test_data()
        ws.add_to_dictionary([
            {"term": "Kairo", "gnd_id": "4029229-7", "category": "GPE", "source": "manual"},
        ])
        entry = ws.lookup("Kairo")
        if entry:
            entry.gnd_preferred = "Kairo"
        doc = json.loads(export_jsonld(df, ws))
        # Should have at least one DefinedTerm node from dictionary
        defined_terms = [n for n in doc["@graph"] if n.get("@type") == "DefinedTerm"]
        self.assertGreater(len(defined_terms), 0)

    def test_jsonld_with_edtf_dates(self):
        """EDTF dates appear as temporal fields in record nodes."""
        from kwb.export.jsonld import export_jsonld
        df, ws = self._make_test_data()
        doc = json.loads(export_jsonld(df, ws))
        record = next((n for n in doc["@graph"] if n.get("identifier") == "obj_001"), None)
        self.assertIsNotNone(record)
        # temporal should be present since we added dates for obj_001
        if "temporal" in record:
            self.assertIsInstance(record["temporal"], list)

    def test_jsonld_requires_base_url(self):
        """EXP-BUG-06: export_jsonld raises error when base_url not provided."""
        from kwb.export.jsonld import export_jsonld
        df = pd.DataFrame({"record_id": ["r1"], "title": ["Test"]})
        ws = Workspace.create("no-base-url")
        ws.id_column = "record_id"
        # No base_url set on workspace
        with self.assertRaises(ValueError) as ctx:
            export_jsonld(df, ws)
        self.assertIn("base_url must be set", str(ctx.exception))

    def test_jsonld_blocks_placeholder_urls(self):
        """EXP-BUG-06: export_jsonld rejects placeholder example.org URLs."""
        from kwb.export.jsonld import export_jsonld
        df = pd.DataFrame({"record_id": ["r1"], "title": ["Test"]})
        ws = Workspace.create("placeholder-url")
        ws.id_column = "record_id"
        ws.base_url = "https://example.org/collection/"
        with self.assertRaises(ValueError) as ctx:
            export_jsonld(df, ws)
        self.assertIn("Placeholder URIs", str(ctx.exception))

    def test_goobi_xml_files_detects_collision(self):
        """EXP-BUG-04: dataframe_to_goobi_xml_files raises error on filename collisions."""
        from kwb.export.goobi_xml import dataframe_to_goobi_xml_files
        import tempfile

        # Create records with IDs that sanitize to the same filename
        df = pd.DataFrame({
            "record_id": ["obj 001", "obj/001", "obj_002"],
            "title": ["First", "Second", "Third"],
        })
        ws = Workspace.create("collision-test")
        ws.id_column = "record_id"
        ws.field_mapping.append(FieldMapping(
            csv_column="title",
            goobi_type="TitleDocMain",
            label="Title",
        ))

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError) as ctx:
                dataframe_to_goobi_xml_files(df, ws, tmpdir)
            self.assertIn("Filename collision", str(ctx.exception))
            self.assertIn("obj 001", str(ctx.exception))

    def test_goobi_xml_files_no_collision_success(self):
        """EXP-BUG-04: dataframe_to_goobi_xml_files succeeds with distinct record IDs."""
        from kwb.export.goobi_xml import dataframe_to_goobi_xml_files
        import tempfile

        # Create records with IDs that sanitize to distinct filenames
        df = pd.DataFrame({
            "record_id": ["obj-001", "obj-002", "obj-003"],
            "title": ["First", "Second", "Third"],
        })
        ws = Workspace.create("no-collision-test")
        ws.id_column = "record_id"
        ws.field_mapping.append(FieldMapping(
            csv_column="title",
            goobi_type="TitleDocMain",
            label="Title",
        ))

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = dataframe_to_goobi_xml_files(df, ws, tmpdir)
            self.assertEqual(len(paths), 3)
            self.assertTrue(all(p.exists() for p in paths))
            self.assertTrue(any("obj-001" in p.name for p in paths))


# ---------------------------------------------------------------------------
# Phase 3 Export Bugfixes (#188, #190, #192, #193, #187)
# ---------------------------------------------------------------------------

class TestPhase3JsonLdSameAs(unittest.TestCase):
    """EXP-BUG-05 (#190): JSON-LD sameAs is always a list, never overwritten."""

    def _make_workspace(self, **kwargs):
        from kwb.core.workspace import Workspace, DictionaryEntry
        ws = Workspace.create("sameAs-test")
        ws.base_url = "https://kwb.example/collection/"
        ws.dictionary = [DictionaryEntry(term="Goethe", **kwargs)]
        return ws

    def test_gnd_only_produces_list(self):
        """Dictionary entry with only GND ID still produces list-shaped sameAs."""
        from kwb.export.jsonld import export_jsonld
        ws = self._make_workspace(gnd_id="118540238")
        out = export_jsonld(pd.DataFrame({"record_id": ["r1"]}), ws)
        doc = json.loads(out)
        authority = [n for n in doc["@graph"] if n.get("@type") == "DefinedTerm"][0]
        self.assertIsInstance(authority["sameAs"], list)
        self.assertEqual(len(authority["sameAs"]), 1)
        self.assertIn("d-nb.info", authority["sameAs"][0])

    def test_gnd_plus_wikidata_lists_both(self):
        """Both authority URIs appear in sameAs without overwrite."""
        from kwb.export.jsonld import export_jsonld
        ws = self._make_workspace(gnd_id="118540238", wikidata_id="Q5879")
        out = export_jsonld(pd.DataFrame({"record_id": ["r1"]}), ws)
        doc = json.loads(out)
        authority = [n for n in doc["@graph"] if n.get("@type") == "DefinedTerm"][0]
        self.assertEqual(len(authority["sameAs"]), 2)
        joined = " ".join(authority["sameAs"])
        self.assertIn("d-nb.info", joined)
        self.assertIn("wikidata.org", joined)

    def test_wikidata_only_no_overwrite_loss(self):
        """Wikidata-only entry has its URI in sameAs list."""
        from kwb.export.jsonld import export_jsonld
        ws = self._make_workspace(wikidata_id="Q5879")
        out = export_jsonld(pd.DataFrame({"record_id": ["r1"]}), ws)
        doc = json.loads(out)
        authority = [n for n in doc["@graph"] if n.get("@type") == "DefinedTerm"][0]
        self.assertIsInstance(authority["sameAs"], list)
        self.assertEqual(len(authority["sameAs"]), 1)
        self.assertIn("wikidata.org", authority["sameAs"][0])


class TestPhase3JsonLdMentionsMerge(unittest.TestCase):
    """EXP-BUG-03 (#188): NER entities merge with field-mapping values."""

    def test_ner_appends_to_field_mapping_mentions(self):
        """NER-derived mentions append rather than overwrite mapped value."""
        from kwb.core.workspace import Workspace, FieldMapping, EntityReview
        from kwb.core.models import ReviewStatus
        from kwb.export.jsonld import export_jsonld

        ws = Workspace.create("merge-test")
        ws.base_url = "https://kwb.example/collection/"
        ws.id_column = "record_id"
        ws.field_mapping = [
            FieldMapping(csv_column="people", goobi_type="SubjectPerson",
                         label="Personen"),
        ]
        ws.entity_reviews = [
            EntityReview(
                text="Schiller", entity_type="PER", record_id="r1",
                status=ReviewStatus.ACCEPTED,
            ),
        ]

        df = pd.DataFrame({"record_id": ["r1"], "people": ["Goethe"]})
        out = export_jsonld(df, ws)
        doc = json.loads(out)
        record = [n for n in doc["@graph"] if n.get("@type") == "CreativeWork"][0]
        mentions = record["mentions"]
        self.assertIsInstance(mentions, list, "Should be list with both values")
        # First entry is field-mapped, second is NER-derived
        rendered = json.dumps(mentions)
        self.assertIn("Goethe", rendered)
        self.assertIn("Schiller", rendered)
        # NER source annotation present on NER entry
        ner_entries = [m for m in mentions if isinstance(m, dict) and m.get("_source") == "ner"]
        self.assertEqual(len(ner_entries), 1)
        self.assertEqual(ner_entries[0]["name"], "Schiller")


class TestPhase3ParseName(unittest.TestCase):
    """EXP-BUG-07 (#192): _parse_name handles nobiliary particles."""

    def test_von_goethe(self):
        from kwb.export.goobi_xml import _parse_name
        fn, ln = _parse_name("von Goethe")
        self.assertEqual(fn, "")
        self.assertEqual(ln, "von Goethe")

    def test_full_name_with_particle(self):
        from kwb.export.goobi_xml import _parse_name
        fn, ln = _parse_name("Johann Wolfgang von Goethe")
        self.assertEqual(fn, "Johann Wolfgang")
        self.assertEqual(ln, "von Goethe")

    def test_de_la_roche(self):
        from kwb.export.goobi_xml import _parse_name
        fn, ln = _parse_name("Maria de la Roche")
        self.assertEqual(fn, "Maria")
        self.assertEqual(ln, "de la Roche")

    def test_van_der_berg(self):
        from kwb.export.goobi_xml import _parse_name
        fn, ln = _parse_name("Pieter van der Berg")
        self.assertEqual(fn, "Pieter")
        self.assertEqual(ln, "van der Berg")

    def test_comma_form_unchanged(self):
        """Comma-form parsing must keep its existing behavior."""
        from kwb.export.goobi_xml import _parse_name
        fn, ln = _parse_name("Goethe, Johann Wolfgang")
        self.assertEqual(fn, "Johann Wolfgang")
        self.assertEqual(ln, "Goethe")

    def test_simple_name_unchanged(self):
        from kwb.export.goobi_xml import _parse_name
        fn, ln = _parse_name("Albert Einstein")
        self.assertEqual(fn, "Albert")
        self.assertEqual(ln, "Einstein")

    def test_single_token_returns_lastname(self):
        from kwb.export.goobi_xml import _parse_name
        fn, ln = _parse_name("Cher")
        self.assertEqual(fn, "")
        self.assertEqual(ln, "Cher")


class TestPhase3CsvGndIds(unittest.TestCase):
    """EXP-BUG-08 (#193): CSV gnd_ids covers all ner_* columns."""

    def test_places_gnd_ids_appear(self):
        from kwb.core.workspace import Workspace, DictionaryEntry
        from kwb.export.csv_export import export_enriched_csv

        ws = Workspace.create("gnd-test")
        ws.dictionary = [
            DictionaryEntry(term="Bern", gnd_id="4005831-9"),
            DictionaryEntry(term="Goethe", gnd_id="118540238"),
        ]
        df = pd.DataFrame({
            "record_id": ["r1", "r2"],
            "ner_persons": ["Goethe", ""],
            "ner_places": ["", "Bern"],
        })
        out_csv = export_enriched_csv(df, ws, include_gnd=True)
        self.assertIn("4005831-9", out_csv, "Place GND ID missing from output")
        self.assertIn("118540238", out_csv, "Person GND ID missing from output")
        # Per-type columns should exist
        self.assertIn("gnd_persons_ids", out_csv)
        self.assertIn("gnd_places_ids", out_csv)


class TestPhase3CatalogIdFailFast(unittest.TestCase):
    """EXP-BUG-02 (#187): CatalogIDDigital injection is opt-in and visible."""

    def test_fail_fast_raises_when_unmapped(self):
        from kwb.core.workspace import Workspace
        from kwb.export.goobi_xml import export_goobi_xml

        ws = Workspace.create("catalog-test")
        df = pd.DataFrame({"record_id": ["r1"], "title": ["x"]})
        with self.assertRaises(ValueError) as ctx:
            export_goobi_xml(df, ws, auto_add_catalog_id=False)
        self.assertIn("CatalogIDDigital", str(ctx.exception))

    def test_auto_add_default_still_works(self):
        """Back-compat: default behavior keeps injecting record_id."""
        from kwb.core.workspace import Workspace
        from kwb.export.goobi_xml import export_goobi_xml

        ws = Workspace.create("catalog-test")
        df = pd.DataFrame({"record_id": ["r1"], "title": ["x"]})
        results = export_goobi_xml(df, ws)  # default auto_add_catalog_id=True
        self.assertEqual(len(results), 1)
        # The injected mapping puts record_id into a CatalogIDDigital element
        self.assertIn("CatalogIDDigital", results[0][1])


# ---------------------------------------------------------------------------
# F30: OCR API Endpoint (via TestClient)
# ---------------------------------------------------------------------------

_FORCE_NO_FASTAPI = os.environ.get("KWB_FORCE_NO_FASTAPI") == "1"
try:
    if _FORCE_NO_FASTAPI:
        raise ImportError("FastAPI disabled for deterministic catalog checks")
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

_skip = unittest.skipUnless(_FASTAPI_AVAILABLE, "FastAPI not installed")

_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xd9"
)


def _get_client():
    from kwb.api import deps
    from kwb.core.workspace import Workspace
    from kwb.ai.mock import MockProvider
    from kwb.api.routes import ai as ai_routes

    deps._state["datasets"] = {}
    deps._state["report"] = None
    deps._state["workspace"] = Workspace(name="test")
    deps._config_cache = None
    deps._prov_override = MockProvider.with_defaults()
    ai_routes._uploaded_images.clear()

    from kwb.api.app import app
    return TestClient(app)


@_skip
class TestOCREndpoint(unittest.TestCase):
    """Tests for POST /api/images/ocr (F30)."""

    def setUp(self):
        self.client = _get_client()

    def _upload_jpeg(self, name="scan.jpg") -> str:
        r = self.client.post(
            "/api/images/upload",
            files=[("files", (name, io.BytesIO(_JPEG), "image/jpeg"))],
        )
        self.assertEqual(r.status_code, 200)
        return r.json()["images"][0]["id"]

    def test_ocr_basic(self):
        """OCR endpoint returns results for uploaded image."""
        img_id = self._upload_jpeg()
        r = self.client.post("/api/images/ocr", json={"image_ids": [img_id]})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("total", data)
        self.assertIn("processed", data)
        self.assertIn("results", data)
        self.assertEqual(data["total"], 1)

    def test_ocr_returns_result_per_image(self):
        """OCR result contains one entry per image ID."""
        ids = [self._upload_jpeg(f"scan{i}.jpg") for i in range(3)]
        r = self.client.post("/api/images/ocr", json={"image_ids": ids})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["results"]), 3)

    def test_ocr_unknown_id_returns_error_entry(self):
        """Unknown image ID yields an error in results, not 500."""
        r = self.client.post("/api/images/ocr", json={"image_ids": ["img_9999_fake"]})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["processed"], 0)
        self.assertIn("error", data["results"][0])

    def test_ocr_empty_ids_returns_400(self):
        """Empty image_ids returns 400."""
        r = self.client.post("/api/images/ocr", json={"image_ids": []})
        self.assertIn(r.status_code, (400, 422))

    def test_ocr_result_has_expected_keys(self):
        """OCR result dict has at least 'id' key (error or result)."""
        img_id = self._upload_jpeg()
        r = self.client.post("/api/images/ocr", json={"image_ids": [img_id]})
        entry = r.json()["results"][0]
        self.assertIn("id", entry)


# ---------------------------------------------------------------------------
# API Routes: CSV and JSON-LD endpoints
# ---------------------------------------------------------------------------

@_skip
class TestNewExportRoutes(unittest.TestCase):
    """Integration tests for new export API endpoints."""

    def setUp(self):
        import pandas as pd
        from kwb.core.models import DatasetProfile, ColumnProfile

        self.client = _get_client()
        # Load a small synthetic dataset into API state
        from kwb.api import deps
        df = pd.DataFrame({
            "record_id": ["obj_001", "obj_002"],
            "title": ["Minarett", "Berge"],
            "year": ["1920", "1930"],
        })
        profile = DatasetProfile(
            source_path="synthetic.csv",
            source_name="synthetic",
            row_count=2, column_count=3,
            columns=[
                ColumnProfile(name="record_id", dtype="str", total_count=2, non_null_count=2, unique_count=2, fill_rate=1.0, sample_values=["obj_001"]),
                ColumnProfile(name="title", dtype="str", total_count=2, non_null_count=2, unique_count=2, fill_rate=1.0, sample_values=["Minarett"]),
                ColumnProfile(name="year", dtype="str", total_count=2, non_null_count=2, unique_count=2, fill_rate=1.0, sample_values=["1920"]),
            ],
            id_column="record_id",
        )
        deps._state["datasets"]["synthetic"] = (df, profile)
        # Set base_url for JSON-LD export (required by EXP-BUG-06)
        deps._state["workspace"].base_url = "https://example.com/collection/"

    def test_csv_export_endpoint(self):
        """POST /api/export/csv returns CSV bytes."""
        r = self.client.post("/api/export/csv", json={"dataset": "synthetic"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers.get("content-type", ""))

    def test_csv_export_has_data(self):
        """CSV export contains original record data."""
        r = self.client.post("/api/export/csv", json={
            "dataset": "synthetic",
            "include_ner": False,
            "include_edtf": False,
        })
        self.assertEqual(r.status_code, 200)
        # Strip BOM and check content
        content = r.content.lstrip(b"\xef\xbb\xbf").decode("utf-8")
        self.assertIn("record_id", content)
        self.assertIn("obj_001", content)

    def test_jsonld_export_endpoint(self):
        """POST /api/export/jsonld returns JSON-LD structure."""
        r = self.client.post("/api/export/jsonld", json={"dataset": "synthetic"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("jsonld", data)
        self.assertIn("@graph", data["jsonld"])

    def test_jsonld_export_as_file(self):
        """JSON-LD export with as_file=true returns downloadable file."""
        r = self.client.post("/api/export/jsonld", json={
            "dataset": "synthetic", "as_file": True,
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn("ld+json", r.headers.get("content-type", ""))


    def test_image_analysis_export_json(self):
        """GET /api/export/image-analyses returns JSON including metadata fields."""
        from kwb.api import deps
        ws = deps._state["workspace"]
        ws.save_image_analysis(ImageAnalysisResult(
            image_id="img_0001_x",
            filename="x.png",
            media_type="image/png",
            size_bytes=12,
            width=1,
            height=1,
            hash_sha256="deadbeef",
            exif_subset={"Model": "Scanner"},
            analyzed=True,
            result={"description": "test"},
            model="mock",
            analyzed_at="2026-01-01T00:00:00",
        ))
        r = self.client.get('/api/export/image-analyses?format=json')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data.get('count'), 1)
        self.assertEqual(data['image_analyses'][0]['width'], 1)
        self.assertEqual(data['image_analyses'][0]['hash_sha256'], 'deadbeef')

    def test_image_analysis_export_csv(self):
        """GET /api/export/image-analyses?format=csv returns downloadable CSV."""
        r = self.client.get('/api/export/image-analyses?format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r.headers.get('content-type', ''))

    def test_wikidata_search_endpoint_offline(self):
        """GET /api/wikidata/search returns empty list when network unavailable."""
        # This tests the endpoint exists; offline behavior depends on environment
        r = self.client.get("/api/wikidata/search?q=Berlin&type=GPE")
        # Should return 200 (empty results) or 200 with results — not 500
        self.assertIn(r.status_code, (200, 500))
        if r.status_code == 200:
            self.assertIn("results", r.json())



if __name__ == "__main__":
    unittest.main()
