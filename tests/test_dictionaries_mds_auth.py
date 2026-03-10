"""
Tests for new Debussy features:
  - Typed dictionaries with record IDs (F1+F2)
  - Dictionary editor / enrichment (F3)
  - MDS validation (F4)
  - Task generation from gaps (F5)
  - User authentication (F6)
  - AI result metadata (F7)
  - Configurable NER (F9)
  - NER→Dictionary pipeline (F10)
  - OCR→NER→Dictionary pipeline (F11)
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestDictionaryType(unittest.TestCase):
    """Feature 1+2: Typed dictionary entries with record IDs."""

    def test_dictionary_entry_has_entry_id(self):
        from kwb.core.workspace import DictionaryEntry
        e = DictionaryEntry(term="Berlin")
        self.assertTrue(len(e.entry_id) == 8)

    def test_dictionary_entry_entity_type(self):
        from kwb.core.workspace import DictionaryEntry
        e = DictionaryEntry(term="Berlin", entity_type="place")
        self.assertEqual(e.entity_type, "place")

    def test_dictionary_entry_record_ids(self):
        from kwb.core.workspace import DictionaryEntry
        e = DictionaryEntry(term="Berlin", record_ids=["R1", "R2"])
        self.assertEqual(e.record_ids, ["R1", "R2"])
        e.add_record_id("R3")
        self.assertIn("R3", e.record_ids)
        e.add_record_id("R1")  # duplicate
        self.assertEqual(e.record_ids.count("R1"), 1)

    def test_dictionary_entry_merge_record_ids(self):
        from kwb.core.workspace import DictionaryEntry
        e = DictionaryEntry(term="Berlin", record_ids=["R1"])
        e.merge_record_ids(["R2", "R3", "R1"])
        self.assertEqual(len(e.record_ids), 3)

    def test_dictionary_entry_preferred_name(self):
        from kwb.core.workspace import DictionaryEntry
        e = DictionaryEntry(term="Bern", preferred_name="Bern (Stadt)")
        self.assertEqual(e.preferred_name, "Bern (Stadt)")

    def test_dictionary_entry_geonames_id(self):
        from kwb.core.workspace import DictionaryEntry
        e = DictionaryEntry(term="Bern", geonames_id="2661552")
        self.assertEqual(e.geonames_id, "2661552")
        self.assertTrue(e.has_authority)

    def test_dictionary_entry_roundtrip(self):
        from kwb.core.workspace import DictionaryEntry
        e = DictionaryEntry(
            term="Zürich", entry_id="abc12345", entity_type="place",
            preferred_name="Zürich (Stadt)", record_ids=["R1", "R2"],
            gnd_id="4068038-1", geonames_id="2657896",
        )
        d = e.to_dict()
        e2 = DictionaryEntry.from_dict(d)
        self.assertEqual(e2.term, "Zürich")
        self.assertEqual(e2.entry_id, "abc12345")
        self.assertEqual(e2.entity_type, "place")
        self.assertEqual(e2.record_ids, ["R1", "R2"])
        self.assertEqual(e2.geonames_id, "2657896")

    def test_dictionary_type_from_entity_type(self):
        from kwb.core.workspace import DictionaryType
        self.assertEqual(DictionaryType.from_entity_type("PER"), DictionaryType.PERSON)
        self.assertEqual(DictionaryType.from_entity_type("LOC"), DictionaryType.PLACE)
        self.assertEqual(DictionaryType.from_entity_type("GPE"), DictionaryType.PLACE)
        self.assertEqual(DictionaryType.from_entity_type("ORG"), DictionaryType.INSTITUTION)


class TestWorkspaceDictionary(unittest.TestCase):
    """Feature 1+2: Workspace dictionary management."""

    def _ws(self):
        from kwb.core.workspace import Workspace
        return Workspace.create("Test")

    def test_add_to_dictionary_with_record_ids(self):
        ws = self._ws()
        ws.add_to_dictionary([
            {"term": "Berlin", "entity_type": "place", "record_id": "R1"},
            {"term": "Berlin", "entity_type": "place", "record_id": "R2"},
            {"term": "München", "entity_type": "place", "record_id": "R3"},
        ])
        self.assertEqual(len(ws.dictionary), 2)
        berlin = ws.lookup("Berlin")
        self.assertIn("R1", berlin.record_ids)
        self.assertIn("R2", berlin.record_ids)

    def test_dictionary_by_type(self):
        ws = self._ws()
        ws.add_to_dictionary([
            {"term": "Berlin", "entity_type": "place"},
            {"term": "Max Müller", "entity_type": "person"},
            {"term": "ETH Zürich", "entity_type": "institution"},
        ])
        places = ws.dictionary_by_type("place")
        self.assertEqual(len(places), 1)
        self.assertEqual(places[0].term, "Berlin")

    def test_export_typed_dictionaries(self):
        ws = self._ws()
        ws.add_to_dictionary([
            {"term": "Berlin", "entity_type": "place"},
            {"term": "Max Müller", "entity_type": "person"},
        ])
        typed = ws.export_typed_dictionaries()
        self.assertIn("place", typed)
        self.assertIn("person", typed)
        self.assertEqual(len(typed["place"]), 1)

    def test_export_dictionary_json(self):
        ws = self._ws()
        ws.add_to_dictionary([
            {"term": "Berlin", "entity_type": "place"},
        ])
        json_str = ws.export_dictionary_json()
        data = json.loads(json_str)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["term"], "Berlin")

    def test_export_dictionary_json_filtered(self):
        ws = self._ws()
        ws.add_to_dictionary([
            {"term": "Berlin", "entity_type": "place"},
            {"term": "Max", "entity_type": "person"},
        ])
        json_str = ws.export_dictionary_json(entity_type="place")
        data = json.loads(json_str)
        self.assertEqual(len(data), 1)

    def test_lookup_by_id(self):
        ws = self._ws()
        ws.add_to_dictionary([{"term": "Bern", "entity_type": "place"}])
        entry = ws.dictionary[0]
        found = ws.lookup_by_id(entry.entry_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.term, "Bern")

    def test_lookup_alternatives(self):
        from kwb.core.workspace import DictionaryEntry
        ws = self._ws()
        e = DictionaryEntry(term="Zürich", alternatives=["Zurich", "Zuerich"])
        ws.add_entry(e)
        self.assertIsNotNone(ws.lookup("Zurich"))

    def test_build_dictionary_from_dataframe(self):
        import pandas as pd
        ws = self._ws()
        df = pd.DataFrame({
            "id": ["R1", "R2", "R3"],
            "ort": ["Berlin", "München", "Berlin"],
        })
        added = ws.build_dictionary_from_dataframe(
            df, ["ort"], entity_type="place", id_column="id",
        )
        self.assertEqual(added, 2)
        berlin = ws.lookup("Berlin")
        self.assertIn("R1", berlin.record_ids)
        self.assertIn("R3", berlin.record_ids)

    def test_workspace_serialization_with_new_fields(self):
        ws = self._ws()
        ws.add_to_dictionary([{"term": "Test", "entity_type": "concept"}])
        ws.tasks = [{"task_id": "t1", "title": "Test Task", "status": "open"}]
        ws.custom_mds_fields = [{"mds_name": "Foo", "goobi_type": "Bar"}]

        d = ws.to_dict()
        self.assertIn("tasks", d)
        self.assertIn("custom_mds_fields", d)

        from kwb.core.workspace import Workspace
        ws2 = Workspace.from_dict(d)
        self.assertEqual(len(ws2.tasks), 1)
        self.assertEqual(len(ws2.custom_mds_fields), 1)
        self.assertEqual(len(ws2.dictionary), 1)
        self.assertEqual(ws2.dictionary[0].entity_type, "concept")


class TestMdsValidation(unittest.TestCase):
    """Feature 4: MDS field validation."""

    def test_validate_mds_all_mapped(self):
        import pandas as pd
        from kwb.core.mds import validate_mds
        from kwb.core.workspace import FieldMapping

        df = pd.DataFrame({
            "id": ["R1", "R2"],
            "titel": ["Foo", "Bar"],
            "typ": ["Bild", "Brief"],
            "ort": ["Bern", "Zürich"],
            "rechte": ["CC-BY", "CC0"],
        })
        mappings = [
            FieldMapping(csv_column="id", goobi_type="CatalogIDDigital"),
            FieldMapping(csv_column="titel", goobi_type="TitleDocMain"),
            FieldMapping(csv_column="typ", goobi_type="DocStruct"),
            FieldMapping(csv_column="ort", goobi_type="PlaceOfPublication"),
            FieldMapping(csv_column="rechte", goobi_type="Rights"),
        ]
        report = validate_mds(df, mappings)
        self.assertEqual(report.required_mapped, 5)
        self.assertEqual(report.required_total, 5)
        self.assertEqual(report.required_filled, 5)

    def test_validate_mds_unmapped(self):
        import pandas as pd
        from kwb.core.mds import validate_mds

        df = pd.DataFrame({"id": ["R1"], "titel": ["Foo"]})
        report = validate_mds(df, [])
        self.assertEqual(report.required_mapped, 0)
        self.assertGreater(report.required_total, 0)

    def test_validate_mds_partial_fill(self):
        import pandas as pd
        from kwb.core.mds import validate_mds
        from kwb.core.workspace import FieldMapping

        df = pd.DataFrame({
            "id": ["R1", "R2", "R3", "R4"],
            "titel": ["Foo", "", "", "Bar"],
        })
        mappings = [
            FieldMapping(csv_column="id", goobi_type="CatalogIDDigital"),
            FieldMapping(csv_column="titel", goobi_type="TitleDocMain"),
        ]
        report = validate_mds(df, mappings)
        titel_field = next(f for f in report.field_results if f.mds_name == "Titel")
        self.assertTrue(titel_field.mapped)
        self.assertAlmostEqual(titel_field.fill_rate, 0.5, places=1)

    def test_validate_mds_custom_fields(self):
        import pandas as pd
        from kwb.core.mds import validate_mds, MdsFieldDef, MdsFieldRequirement

        df = pd.DataFrame({"id": ["R1"], "farbe": ["Rot"]})
        from kwb.core.workspace import FieldMapping
        mappings = [FieldMapping(csv_column="farbe", goobi_type="CustomColor")]
        custom = [MdsFieldDef("Farbe", "CustomColor", MdsFieldRequirement.RECOMMENDED)]
        report = validate_mds(df, mappings, custom_fields=custom)
        farbe = next(f for f in report.field_results if f.mds_name == "Farbe")
        self.assertTrue(farbe.mapped)

    def test_completeness_score(self):
        import pandas as pd
        from kwb.core.mds import validate_mds
        from kwb.core.workspace import FieldMapping

        df = pd.DataFrame({"id": ["R1", "R2"], "titel": ["A", "B"]})
        mappings = [
            FieldMapping(csv_column="id", goobi_type="CatalogIDDigital"),
            FieldMapping(csv_column="titel", goobi_type="TitleDocMain"),
        ]
        report = validate_mds(df, mappings)
        self.assertGreater(report.completeness_score, 0)
        self.assertLessEqual(report.completeness_score, 1.0)


class TestTaskGeneration(unittest.TestCase):
    """Feature 5: Task generation from MDS gaps."""

    def test_generate_tasks_from_unmapped_required(self):
        import pandas as pd
        from kwb.core.mds import validate_mds
        from kwb.core.tasks import generate_tasks_from_mds

        df = pd.DataFrame({"id": ["R1"], "titel": ["Foo"]})
        report = validate_mds(df, [])
        tasks = generate_tasks_from_mds(report)
        self.assertGreater(len(tasks), 0)
        map_tasks = [t for t in tasks if t.category.value == "map_field"]
        self.assertGreater(len(map_tasks), 0)

    def test_generate_tasks_sorted_by_priority(self):
        import pandas as pd
        from kwb.core.mds import validate_mds
        from kwb.core.tasks import generate_tasks_from_mds

        df = pd.DataFrame({"id": ["R1"]})
        report = validate_mds(df, [])
        tasks = generate_tasks_from_mds(report)
        priorities = [t.priority for t in tasks]
        self.assertEqual(priorities, sorted(priorities))

    def test_task_roundtrip(self):
        from kwb.core.tasks import CurationTask, TaskCategory, TaskStatus
        t = CurationTask(
            title="Test", category=TaskCategory.MAP_FIELD,
            priority=1, mds_field="Titel",
        )
        d = t.to_dict()
        t2 = CurationTask.from_dict(d)
        self.assertEqual(t2.title, "Test")
        self.assertEqual(t2.category, TaskCategory.MAP_FIELD)
        self.assertEqual(t2.status, TaskStatus.OPEN)

    def test_task_complete(self):
        from kwb.core.tasks import CurationTask, TaskStatus
        t = CurationTask(title="Test")
        t.complete("Done!")
        self.assertEqual(t.status, TaskStatus.DONE)
        self.assertTrue(t.completed_at)


class TestAuthentication(unittest.TestCase):
    """Feature 6: Simple user authentication."""

    def test_create_and_authenticate(self):
        from kwb.core.auth import UserStore
        store = UserStore()
        store.create_user("testuser", "secret123", display_name="Test")
        session = store.authenticate("testuser", "secret123")
        self.assertIsNotNone(session)
        self.assertTrue(len(session.token) > 20)

    def test_wrong_password(self):
        from kwb.core.auth import UserStore
        store = UserStore()
        store.create_user("user1", "correct")
        self.assertIsNone(store.authenticate("user1", "wrong"))

    def test_session_validation(self):
        from kwb.core.auth import UserStore
        store = UserStore()
        store.create_user("user1", "pass123")
        session = store.authenticate("user1", "pass123")
        user = store.validate_session(session.token)
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "user1")

    def test_logout(self):
        from kwb.core.auth import UserStore
        store = UserStore()
        store.create_user("user1", "pass123")
        session = store.authenticate("user1", "pass123")
        self.assertTrue(store.logout(session.token))
        self.assertIsNone(store.validate_session(session.token))

    def test_duplicate_user(self):
        from kwb.core.auth import UserStore
        store = UserStore()
        store.create_user("user1", "pass")
        with self.assertRaises(ValueError):
            store.create_user("user1", "pass2")

    def test_ensure_default_admin(self):
        from kwb.core.auth import UserStore
        store = UserStore()
        created = store.ensure_default_admin()
        self.assertTrue(created)
        self.assertEqual(store.user_count(), 1)
        self.assertFalse(store.ensure_default_admin())

    def test_file_persistence(self):
        from kwb.core.auth import UserStore
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store1 = UserStore(path)
            store1.create_user("user1", "pw1")
            store2 = UserStore(path)
            self.assertEqual(store2.user_count(), 1)
            self.assertIsNotNone(store2.authenticate("user1", "pw1"))
        finally:
            os.unlink(path)


class TestConfigurableNER(unittest.TestCase):
    """Feature 9: NER entity type filtering."""

    def test_ner_hybrid_entity_types_filter(self):
        import pandas as pd
        from kwb.analyze.ner import ner_hybrid

        df = pd.DataFrame({
            "id": ["R1"],
            "text": ["Max Müller aus Berlin am 01.01.2020"],
        })
        result = ner_hybrid(
            df, ["text"], id_column="id",
            use_spacy=False, use_llm=False,
            entity_types=["PER"],
        )
        self.assertIsNotNone(result)
        self.assertEqual(len(result.entities), 0)

    def test_entity_type_mapping(self):
        from kwb.core.workspace import DictionaryType
        self.assertEqual(
            DictionaryType.from_entity_type("PER").value, "person",
        )
        self.assertEqual(
            DictionaryType.from_entity_type("LOC").value, "place",
        )
        self.assertEqual(
            DictionaryType.from_entity_type("ORG").value, "institution",
        )


class TestAIProvenance(unittest.TestCase):
    """Feature 7: AI result metadata."""

    def test_entity_has_reasoning(self):
        from kwb.analyze.ner import Entity, EntityType
        e = Entity(
            text="Berlin", entity_type=EntityType.LOC,
            confidence=0.95, reasoning="Capital of Germany",
            source="llm",
        )
        self.assertEqual(e.reasoning, "Capital of Germany")
        self.assertEqual(e.confidence, 0.95)
        self.assertEqual(e.source, "llm")

    def test_ner_result_dict_includes_reasoning(self):
        from kwb.analyze.ner import Entity, EntityType, NERResult
        result = NERResult(entities=[
            Entity(
                text="Berlin", entity_type=EntityType.LOC,
                confidence=0.9, reasoning="City name",
            ),
        ])
        dicts = result.to_dict_list()
        self.assertEqual(dicts[0]["reasoning"], "City name")
        self.assertEqual(dicts[0]["confidence"], 0.9)


if __name__ == "__main__":
    unittest.main()
