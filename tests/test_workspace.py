"""
Tests for core/workspace.py.

Covers:
- FieldMapping: is_ignored, to_dict/from_dict roundtrip.
- DictionaryEntry: has_authority, lookup.
- EntityReview: accept/reject lifecycle.
- Workspace: CRUD operations, serialization roundtrip, review stats.
- add_entities: deduplication, skip exact duplicates.
- active_mappings: filters disabled and ignored.
"""

import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import unittest

from kwb.core.workspace import (
    Workspace, FieldMapping, GoobiMetadataType, DictionaryEntry,
    EntityReview, ReviewStatus,
)


class TestFieldMapping(unittest.TestCase):

    def test_not_ignored_by_default(self):
        m = FieldMapping(csv_column="title", goobi_type="TitleDocMain")
        self.assertFalse(m.is_ignored)

    def test_ignored_when_disabled(self):
        m = FieldMapping(csv_column="internal", goobi_type="TitleDocMain", enabled=False)
        self.assertTrue(m.is_ignored)

    def test_ignored_when_type_is_ignore_sentinel(self):
        m = FieldMapping(csv_column="junk", goobi_type=GoobiMetadataType.IGNORE.value)
        self.assertTrue(m.is_ignored)

    def test_roundtrip(self):
        m = FieldMapping(
            csv_column="subject", goobi_type="SubjectTopic",
            repeatable=True, authority="gnd",
            authority_uri="http://d-nb.info/gnd/",
            note="LCSH term",
        )
        self.assertEqual(FieldMapping.from_dict(m.to_dict()), m)


class TestDictionaryEntry(unittest.TestCase):

    def test_has_authority_with_gnd(self):
        e = DictionaryEntry(term="Berlin", gnd_id="4005765-8")
        self.assertTrue(e.has_authority)

    def test_has_authority_with_wikidata(self):
        e = DictionaryEntry(term="Berlin", wikidata_id="Q64")
        self.assertTrue(e.has_authority)

    def test_no_authority(self):
        e = DictionaryEntry(term="Unbekannt")
        self.assertFalse(e.has_authority)

    def test_roundtrip(self):
        e = DictionaryEntry(
            term="Berlin", gnd_id="4005765-8",
            gnd_preferred="Berlin", gnd_type="PlaceOrGeographicName",
            alternatives=["West-Berlin", "Ost-Berlin"],
            confidence=0.95, source="api",
        )
        restored = DictionaryEntry.from_dict(e.to_dict())
        self.assertEqual(restored.term, e.term)
        self.assertEqual(restored.gnd_id, e.gnd_id)
        self.assertEqual(restored.alternatives, e.alternatives)


class TestEntityReview(unittest.TestCase):

    def _make(self):
        return EntityReview(text="Berlin", entity_type="GPE", record_id="r1")

    def test_initial_status_pending(self):
        self.assertEqual(self._make().status, ReviewStatus.PENDING)

    def test_accept_changes_status(self):
        er = self._make()
        er.accept(gnd_id="4005765-8", gnd_preferred="Berlin", note="Klar")
        self.assertEqual(er.status, ReviewStatus.ACCEPTED)
        self.assertEqual(er.gnd_id, "4005765-8")
        self.assertNotEqual(er.reviewed_at, "")

    def test_reject_changes_status(self):
        er = self._make()
        er.reject(note="Falsch")
        self.assertEqual(er.status, ReviewStatus.REJECTED)
        self.assertEqual(er.reviewer_note, "Falsch")

    def test_dedup_key_case_insensitive(self):
        a = EntityReview(text="Berlin", entity_type="GPE", record_id="r1")
        b = EntityReview(text="berlin", entity_type="GPE", record_id="r1")
        self.assertEqual(a.dedup_key, b.dedup_key)

    def test_roundtrip(self):
        er = self._make()
        er.accept(gnd_id="4005765-8", note="confirmed")
        restored = EntityReview.from_dict(er.to_dict())
        self.assertEqual(restored.status, ReviewStatus.ACCEPTED)
        self.assertEqual(restored.gnd_id, "4005765-8")


class TestWorkspace(unittest.TestCase):

    def _ws(self):
        return Workspace.create("Test GIUB", source_file="data.csv")

    # --- Basic properties ---
    def test_create(self):
        ws = self._ws()
        self.assertEqual(ws.name, "Test GIUB")
        self.assertEqual(ws.source_file, "data.csv")
        self.assertNotEqual(ws.created_at, "")

    # --- Field mapping ---
    def test_set_field_mapping(self):
        ws = self._ws()
        mappings = [
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("title", "TitleDocMain"),
        ]
        ws.set_field_mapping(mappings)
        self.assertEqual(len(ws.field_mapping), 2)

    def test_get_mapping_by_column(self):
        ws = self._ws()
        ws.set_field_mapping([FieldMapping("title", "TitleDocMain")])
        m = ws.get_mapping("title")
        self.assertIsNotNone(m)
        self.assertEqual(m.goobi_type, "TitleDocMain")

    def test_get_mapping_missing_returns_none(self):
        ws = self._ws()
        self.assertIsNone(ws.get_mapping("nonexistent"))

    def test_active_mappings_excludes_disabled(self):
        ws = self._ws()
        ws.set_field_mapping([
            FieldMapping("title", "TitleDocMain", enabled=True),
            FieldMapping("internal", "TitleDocMain", enabled=False),
            FieldMapping("junk", GoobiMetadataType.IGNORE.value),
        ])
        active = ws.active_mappings()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].csv_column, "title")

    def test_add_or_update_mapping_updates_existing(self):
        ws = self._ws()
        ws.set_field_mapping([FieldMapping("title", "TitleDocMain")])
        ws.add_or_update_mapping(FieldMapping("title", "Description"))
        self.assertEqual(len(ws.field_mapping), 1)
        self.assertEqual(ws.field_mapping[0].goobi_type, "Description")

    def test_add_or_update_mapping_appends_new(self):
        ws = self._ws()
        ws.set_field_mapping([FieldMapping("title", "TitleDocMain")])
        ws.add_or_update_mapping(FieldMapping("year", "PublicationYear"))
        self.assertEqual(len(ws.field_mapping), 2)

    # --- Dictionary ---
    def test_add_and_lookup_entry(self):
        ws = self._ws()
        e = DictionaryEntry(term="Berlin", gnd_id="4005765-8")
        ws.add_entry(e)
        found = ws.lookup("Berlin")
        self.assertIsNotNone(found)
        self.assertEqual(found.gnd_id, "4005765-8")

    def test_lookup_case_insensitive(self):
        ws = self._ws()
        ws.add_entry(DictionaryEntry(term="Berlin", gnd_id="4005765-8"))
        self.assertIsNotNone(ws.lookup("BERLIN"))
        self.assertIsNotNone(ws.lookup("berlin"))

    def test_lookup_gnd_id(self):
        ws = self._ws()
        ws.add_entry(DictionaryEntry(term="Berlin", gnd_id="4005765-8"))
        found = ws.lookup_gnd("4005765-8")
        self.assertIsNotNone(found)

    def test_lookup_missing_returns_none(self):
        ws = self._ws()
        self.assertIsNone(ws.lookup("NoSuchPlace"))

    # --- Entity reviews ---
    def test_add_entities_from_ner_dict_list(self):
        ws = self._ws()
        entities = [
            {"text": "Berlin", "type": "GPE", "record_id": "r1",
             "gnd_id": None, "gnd_preferred": None},
            {"text": "München", "type": "GPE", "record_id": "r1",
             "gnd_id": None, "gnd_preferred": None},
        ]
        added = ws.add_entities(entities)
        self.assertEqual(added, 2)
        self.assertEqual(len(ws.entity_reviews), 2)

    def test_add_entities_skips_exact_duplicates(self):
        ws = self._ws()
        ent = [{"text": "Berlin", "type": "GPE", "record_id": "r1",
                "gnd_id": None, "gnd_preferred": None}]
        ws.add_entities(ent)
        added = ws.add_entities(ent)  # duplicate
        self.assertEqual(added, 0)
        self.assertEqual(len(ws.entity_reviews), 1)

    def test_add_entities_different_records_not_duplicate(self):
        ws = self._ws()
        ws.add_entities([{"text": "Berlin", "type": "GPE", "record_id": "r1",
                          "gnd_id": None, "gnd_preferred": None}])
        ws.add_entities([{"text": "Berlin", "type": "GPE", "record_id": "r2",
                          "gnd_id": None, "gnd_preferred": None}])
        self.assertEqual(len(ws.entity_reviews), 2)

    def test_reviews_by_status(self):
        ws = self._ws()
        ws.add_entities([
            {"text": "Berlin", "type": "GPE", "record_id": "r1",
             "gnd_id": None, "gnd_preferred": None},
            {"text": "Wien", "type": "GPE", "record_id": "r2",
             "gnd_id": None, "gnd_preferred": None},
        ])
        ws.entity_reviews[0].accept()
        pending = ws.reviews_by_status(ReviewStatus.PENDING)
        accepted = ws.reviews_by_status(ReviewStatus.ACCEPTED)
        self.assertEqual(len(pending), 1)
        self.assertEqual(len(accepted), 1)

    def test_review_stats(self):
        ws = self._ws()
        ws.add_entities([
            {"text": "A", "type": "LOC", "record_id": "r1",
             "gnd_id": None, "gnd_preferred": None},
            {"text": "B", "type": "LOC", "record_id": "r2",
             "gnd_id": None, "gnd_preferred": None},
        ])
        ws.entity_reviews[0].accept()
        stats = ws.review_stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["pending"], 1)

    # --- Serialization ---
    def test_to_json_is_valid_json(self):
        ws = self._ws()
        ws.set_field_mapping([FieldMapping("title", "TitleDocMain")])
        ws.add_entry(DictionaryEntry(term="Berlin", gnd_id="4005765-8"))
        j = ws.to_json()
        data = json.loads(j)
        self.assertEqual(data["name"], "Test GIUB")

    def test_roundtrip_json(self):
        ws = self._ws()
        ws.set_field_mapping([FieldMapping("title", "TitleDocMain", repeatable=True)])
        ws.add_entry(DictionaryEntry(term="Zürich", gnd_id="2661604-8"))
        ws.add_entities([{"text": "Zürich", "type": "GPE", "record_id": "r1",
                          "gnd_id": "2661604-8", "gnd_preferred": "Zürich"}])
        ws.model_text = "gpt-oss-120b"

        restored = Workspace.from_json(ws.to_json())
        self.assertEqual(restored.name, ws.name)
        self.assertEqual(len(restored.field_mapping), 1)
        self.assertTrue(restored.field_mapping[0].repeatable)
        self.assertIsNotNone(restored.lookup("Zürich"))
        self.assertEqual(len(restored.entity_reviews), 1)
        self.assertEqual(restored.model_text, "gpt-oss-120b")

    def test_updated_at_changes_on_mutation(self):
        import time
        ws = self._ws()
        t0 = ws.updated_at
        time.sleep(0.01)
        ws.add_entry(DictionaryEntry(term="Test"))
        self.assertGreater(ws.updated_at, t0)

    def test_save_and_load(self):
        import tempfile
        import os
        ws = self._ws()
        ws.set_field_mapping([FieldMapping("record_id", "CatalogIDDigital")])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            ws.save(path)
            loaded = Workspace.load(path)
            self.assertEqual(loaded.name, ws.name)
            self.assertEqual(len(loaded.field_mapping), 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
