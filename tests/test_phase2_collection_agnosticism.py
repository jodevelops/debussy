"""
Phase 2: Collection-Agnosticism Regression Tests

Tests for audit issues #103, #110, #120, #121, #136.
Each test is annotated with the audit ID it addresses.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kwb.core.workspace import (
    AuthorityCandidate,
    CuratedDate,
    DictionaryEntry,
    EntityReview,
    FieldMapping,
    ImageAnalysisResult,
    Workspace,
)


class TestIssue103FieldMappingConsolidation(unittest.TestCase):
    """CORE-BUG-03 (#103): Consolidate dual list/dict storage for field_mapping.

    Previous issue:
    - field_mapping property accepted both dict and list formats
    - _field_mapping_raw held dict format, _field_mapping held list format
    - Getter returned _field_mapping_raw if present (inconsistent type)
    - Cross-module code couldn't rely on type (dict vs FieldMapping list)

    Fix:
    - Remove _field_mapping_raw completely
    - Canonical format is always list[FieldMapping]
    - Legacy dict format is migrated to list on load/set
    - Serialization always uses list format
    """

    def test_01_field_mapping_always_returns_list(self):
        """CORE-BUG-03: field_mapping property always returns list[FieldMapping]."""
        ws = Workspace()
        self.assertIsInstance(ws.field_mapping, list)
        self.assertEqual(len(ws.field_mapping), 0)

    def test_02_set_list_format_stores_as_list(self):
        """CORE-BUG-03: Setting list[FieldMapping] format works correctly."""
        ws = Workspace()
        mappings = [
            FieldMapping(csv_column="title", goobi_type="TitleDocMain", label="Titel"),
            FieldMapping(csv_column="date", goobi_type="PublicationYear", label="Datum"),
        ]
        ws.field_mapping = mappings

        self.assertEqual(len(ws.field_mapping), 2)
        self.assertIsInstance(ws.field_mapping[0], FieldMapping)
        self.assertEqual(ws.field_mapping[0].csv_column, "title")
        self.assertEqual(ws.field_mapping[0].label, "Titel")

    def test_03_set_dict_format_converts_to_list(self):
        """CORE-BUG-03: Setting legacy dict format converts to canonical list."""
        ws = Workspace()
        legacy_dict = {
            "title": ("Titel", "TitleDocMain"),
            "date": ("Datum", "PublicationYear"),
        }
        ws.field_mapping = legacy_dict

        # Result should be list[FieldMapping], not dict
        self.assertIsInstance(ws.field_mapping, list)
        self.assertEqual(len(ws.field_mapping), 2)

        # Verify all items are FieldMapping objects
        for item in ws.field_mapping:
            self.assertIsInstance(item, FieldMapping)

        # Verify data was preserved from dict format
        cols = {m.csv_column for m in ws.field_mapping}
        self.assertEqual(cols, {"title", "date"})

    def test_04_dict_with_list_values_converts_correctly(self):
        """CORE-BUG-03: Dict with list values (not just tuples) converts."""
        ws = Workspace()
        ws.field_mapping = {
            "title": ["Titel", "TitleDocMain"],  # list, not tuple
        }

        self.assertEqual(len(ws.field_mapping), 1)
        self.assertEqual(ws.field_mapping[0].csv_column, "title")
        self.assertEqual(ws.field_mapping[0].label, "Titel")

    def test_05_to_dict_serializes_as_list(self):
        """CORE-BUG-03: to_dict() always serializes field_mapping as list."""
        ws = Workspace(name="test")
        ws.field_mapping = [
            FieldMapping(csv_column="title", goobi_type="TitleDocMain", label="Titel"),
        ]

        d = ws.to_dict()

        # Verify field_mapping in dict is a list
        self.assertIsInstance(d["field_mapping"], list)
        self.assertEqual(len(d["field_mapping"]), 1)

        # Verify element is a dict (from to_dict()) not a FieldMapping object
        self.assertIsInstance(d["field_mapping"][0], dict)
        self.assertEqual(d["field_mapping"][0]["csv_column"], "title")

    def test_06_roundtrip_list_format_preserved(self):
        """CORE-BUG-03: Save/load with list format preserves all data."""
        original = Workspace(name="test-list")
        original.field_mapping = [
            FieldMapping(
                csv_column="title",
                goobi_type="TitleDocMain",
                label="Titel",
                repeatable=False,
                authority="",
                enabled=True,
            ),
        ]

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            original.save(path)
            loaded = Workspace.load(path)

            self.assertEqual(len(loaded.field_mapping), 1)
            self.assertEqual(loaded.field_mapping[0].csv_column, "title")
            self.assertEqual(loaded.field_mapping[0].label, "Titel")
            self.assertEqual(loaded.field_mapping[0].goobi_type, "TitleDocMain")
        finally:
            Path(path).unlink()

    def test_07_roundtrip_legacy_dict_format_migrated(self):
        """CORE-BUG-03: Save/load with legacy dict format migrates to list."""
        original = Workspace(name="test-dict")
        original.field_mapping = {
            "title": ("Titel", "TitleDocMain"),
            "date": ("Datum", "PublicationYear"),
        }

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            original.save(path)
            loaded = Workspace.load(path)

            # Result should be list format
            self.assertIsInstance(loaded.field_mapping, list)
            self.assertEqual(len(loaded.field_mapping), 2)

            # Verify data is accessible
            cols = {m.csv_column for m in loaded.field_mapping}
            self.assertEqual(cols, {"title", "date"})
        finally:
            Path(path).unlink()

    def test_08_json_with_dict_format_converts_on_from_dict(self):
        """CORE-BUG-03: from_dict() handles legacy dict JSON format."""
        legacy_json_dict = {
            "name": "legacy-project",
            "field_mapping": {
                "title": ["Titel", "TitleDocMain"],
                "author": ["Autor", "Creator"],
            },
            "dictionary": [],
            "entity_reviews": [],
            "dates": [],
            "source_files": [],
        }

        ws = Workspace.from_dict(legacy_json_dict)

        # Should convert to list format
        self.assertIsInstance(ws.field_mapping, list)
        self.assertEqual(len(ws.field_mapping), 2)

    def test_09_active_mappings_returns_list(self):
        """CORE-BUG-03: active_mappings() returns list[FieldMapping]."""
        ws = Workspace()
        ws.field_mapping = [
            FieldMapping(csv_column="title", goobi_type="TitleDocMain", enabled=True),
            FieldMapping(csv_column="ignore_me", goobi_type="__ignore__", enabled=True),
        ]

        active = ws.active_mappings()

        self.assertIsInstance(active, list)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].csv_column, "title")

    def test_10_get_mapping_returns_field_mapping(self):
        """CORE-BUG-03: get_mapping() returns FieldMapping object."""
        ws = Workspace()
        ws.field_mapping = [
            FieldMapping(csv_column="title", goobi_type="TitleDocMain", label="Titel"),
        ]

        mapping = ws.get_mapping("title")

        self.assertIsInstance(mapping, FieldMapping)
        self.assertEqual(mapping.label, "Titel")

    def test_11_add_or_update_mapping_preserves_list(self):
        """CORE-BUG-03: add_or_update_mapping() keeps field_mapping as list."""
        ws = Workspace()
        ws.field_mapping = [
            FieldMapping(csv_column="title", goobi_type="TitleDocMain"),
        ]

        new_mapping = FieldMapping(
            csv_column="author",
            goobi_type="Creator",
            label="Autor",
        )
        ws.add_or_update_mapping(new_mapping)

        self.assertEqual(len(ws.field_mapping), 2)
        self.assertIsInstance(ws.field_mapping[1], FieldMapping)

    def test_12_empty_field_mapping_handles_correctly(self):
        """CORE-BUG-03: Empty field_mapping is stored as empty list."""
        ws = Workspace()

        self.assertEqual(ws.field_mapping, [])
        self.assertIsInstance(ws.field_mapping, list)

    def test_13_direct_assignment_of_field_mapping_objects(self):
        """CORE-BUG-03: Direct FieldMapping objects in dict are preserved."""
        ws = Workspace()
        fm = FieldMapping(csv_column="title", goobi_type="TitleDocMain")
        ws.field_mapping = {"title": fm}

        # Should still be list
        self.assertIsInstance(ws.field_mapping, list)
        self.assertEqual(len(ws.field_mapping), 1)
        self.assertEqual(ws.field_mapping[0].csv_column, "title")

    def test_14_set_field_mapping_helper_stores_list(self):
        """CORE-BUG-03: set_field_mapping() stores as list."""
        ws = Workspace()
        mappings = [
            FieldMapping(csv_column="title", goobi_type="TitleDocMain"),
        ]
        ws.set_field_mapping(mappings)

        self.assertIsInstance(ws.field_mapping, list)
        self.assertEqual(len(ws.field_mapping), 1)

    def test_15_to_summary_uses_internal_list(self):
        """CORE-BUG-03: to_summary() mapping_count uses _field_mapping."""
        ws = Workspace(name="test")
        ws.field_mapping = [
            FieldMapping(csv_column="title", goobi_type="TitleDocMain"),
            FieldMapping(csv_column="date", goobi_type="PublicationYear"),
        ]

        summary = ws.to_summary()

        self.assertEqual(summary["mapping_count"], 2)


class TestIssue110ProvenanceConsistency(unittest.TestCase):
    """CORE-ENH-03 (#110): Provenance field consistency across extraction types.

    Previous issue:
    - Different extraction types had different provenance fields
    - DictionaryEntry: source/model_source/last_edited
    - AuthorityCandidate: source/reviewed_at (no model)
    - EntityReview: source/reviewed_at (no model, no extracted_at)
    - CuratedDate: method only (no source, model, extracted_at, reviewed_at)
    - ImageAnalysisResult: had property `provenance` with different shape
    - `source` field had different meanings across types

    Fix:
    - Define canonical Provenance TypedDict in core/models.py
    - Add provenance() method to all five extraction types
    - All provenance() methods return uniform dict with same keys
    - Add missing fields (model, extracted_at, reviewed_at, reviewer)
    """

    PROVENANCE_KEYS = {
        "source", "method", "model", "extracted_at",
        "reviewed_at", "reviewer", "note",
    }

    def test_01_dictionary_entry_provenance_keys(self):
        """CORE-ENH-03: DictionaryEntry.provenance() has canonical keys."""
        entry = DictionaryEntry(
            term="Bern",
            source="api",
            model_source="qwen3-coder",
            note="GND match",
        )
        prov = entry.provenance()
        self.assertEqual(set(prov.keys()), self.PROVENANCE_KEYS)
        self.assertEqual(prov["source"], "api")
        self.assertEqual(prov["model"], "qwen3-coder")
        self.assertEqual(prov["note"], "GND match")

    def test_02_authority_candidate_provenance_keys(self):
        """CORE-ENH-03: AuthorityCandidate.provenance() has canonical keys."""
        cand = AuthorityCandidate(
            entry_id="e1",
            source="gnd",
            authority_id="4005762-8",
            model="qwen3-coder",
        )
        prov = cand.provenance()
        self.assertEqual(set(prov.keys()), self.PROVENANCE_KEYS)
        self.assertEqual(prov["source"], "gnd")
        self.assertEqual(prov["method"], "api")
        self.assertEqual(prov["model"], "qwen3-coder")
        # extracted_at auto-populated in __post_init__
        self.assertTrue(prov["extracted_at"])

    def test_03_authority_candidate_extracted_at_auto_populated(self):
        """CORE-ENH-03: AuthorityCandidate.extracted_at auto-populates."""
        cand = AuthorityCandidate(entry_id="e1", source="gnd")
        self.assertTrue(cand.extracted_at)
        self.assertIn("+00:00", cand.extracted_at)

    def test_04_entity_review_provenance_keys(self):
        """CORE-ENH-03: EntityReview.provenance() has canonical keys."""
        er = EntityReview(
            text="Bern",
            entity_type="GPE",
            source="llm",
            model="qwen3-coder",
        )
        prov = er.provenance()
        self.assertEqual(set(prov.keys()), self.PROVENANCE_KEYS)
        self.assertEqual(prov["source"], "llm")
        self.assertEqual(prov["method"], "llm")
        self.assertEqual(prov["model"], "qwen3-coder")
        self.assertTrue(prov["extracted_at"])

    def test_05_entity_review_extracted_at_auto_populated(self):
        """CORE-ENH-03: EntityReview.extracted_at auto-populates."""
        er = EntityReview(text="Test", entity_type="PER")
        self.assertTrue(er.extracted_at)
        self.assertIn("+00:00", er.extracted_at)

    def test_06_curated_date_provenance_keys(self):
        """CORE-ENH-03: CuratedDate.provenance() has canonical keys."""
        cd = CuratedDate(
            original="ca. 1920",
            edtf="1920~",
            method="rule",
            confidence=0.95,
        )
        prov = cd.provenance()
        self.assertEqual(set(prov.keys()), self.PROVENANCE_KEYS)
        # Method mirrors into source if source not set
        self.assertEqual(prov["source"], "rule")
        self.assertEqual(prov["method"], "rule")
        self.assertTrue(prov["extracted_at"])

    def test_07_curated_date_extracted_at_auto_populated(self):
        """CORE-ENH-03: CuratedDate.extracted_at auto-populates."""
        cd = CuratedDate(original="1900", method="rule")
        self.assertTrue(cd.extracted_at)
        self.assertIn("+00:00", cd.extracted_at)

    def test_08_image_analysis_provenance_keys(self):
        """CORE-ENH-03: ImageAnalysisResult.provenance() has canonical keys."""
        img = ImageAnalysisResult(
            image_id="img1",
            model="qwen3-vl",
            analyzed_at="2026-05-05T12:00:00+00:00",
            reviewer="alice",
        )
        prov = img.provenance()
        self.assertEqual(set(prov.keys()), self.PROVENANCE_KEYS)
        self.assertEqual(prov["source"], "vision_ai")
        self.assertEqual(prov["method"], "llm")
        self.assertEqual(prov["model"], "qwen3-vl")
        self.assertEqual(prov["extracted_at"], "2026-05-05T12:00:00+00:00")
        self.assertEqual(prov["reviewer"], "alice")

    def test_09_image_analysis_provenance_is_method_not_property(self):
        """CORE-ENH-03: provenance() is a method (not property) for consistency."""
        img = ImageAnalysisResult(image_id="img1", model="qwen3-vl")
        # Should be callable, not a property
        result = img.provenance()
        self.assertIsInstance(result, dict)

    def test_10_all_extraction_types_have_provenance_method(self):
        """CORE-ENH-03: All extraction types expose provenance() method."""
        types_to_check = [
            DictionaryEntry(term="Test"),
            AuthorityCandidate(entry_id="e1"),
            EntityReview(text="Test", entity_type="PER"),
            CuratedDate(original="1900"),
            ImageAnalysisResult(image_id="img1"),
        ]
        for obj in types_to_check:
            self.assertTrue(
                callable(getattr(obj, "provenance", None)),
                f"{type(obj).__name__} missing callable provenance() method",
            )
            prov = obj.provenance()
            self.assertIsInstance(prov, dict)
            self.assertEqual(
                set(prov.keys()), self.PROVENANCE_KEYS,
                f"{type(obj).__name__}.provenance() has wrong keys",
            )

    def test_11_provenance_uniform_shape_across_types(self):
        """CORE-ENH-03: All provenance() return same key set for uniform consumption."""
        prov_shapes = []
        objs = [
            DictionaryEntry(term="Test"),
            AuthorityCandidate(entry_id="e1"),
            EntityReview(text="Test", entity_type="PER"),
            CuratedDate(original="1900"),
            ImageAnalysisResult(image_id="img1"),
        ]
        for obj in objs:
            prov_shapes.append(set(obj.provenance().keys()))

        # All shapes must be identical
        first_shape = prov_shapes[0]
        for i, shape in enumerate(prov_shapes[1:], 1):
            self.assertEqual(
                shape, first_shape,
                f"Shape mismatch between {type(objs[0]).__name__} and {type(objs[i]).__name__}",
            )

    def test_12_entity_review_serialization_includes_provenance_fields(self):
        """CORE-ENH-03: EntityReview to_dict/from_dict roundtrip preserves provenance."""
        original = EntityReview(
            text="Bern",
            entity_type="GPE",
            source="llm",
            model="qwen3-coder",
            reviewer="alice",
        )
        d = original.to_dict()
        self.assertIn("model", d)
        self.assertIn("extracted_at", d)
        self.assertIn("reviewer", d)

        restored = EntityReview.from_dict(d)
        self.assertEqual(restored.model, "qwen3-coder")
        self.assertEqual(restored.reviewer, "alice")
        self.assertEqual(restored.extracted_at, original.extracted_at)

    def test_13_curated_date_serialization_includes_provenance_fields(self):
        """CORE-ENH-03: CuratedDate to_dict/from_dict roundtrip preserves provenance."""
        original = CuratedDate(
            original="ca. 1920",
            edtf="1920~",
            method="llm",
            model="qwen3-coder",
            reviewer="alice",
        )
        d = original.to_dict()
        self.assertIn("source", d)
        self.assertIn("model", d)
        self.assertIn("extracted_at", d)
        self.assertIn("reviewed_at", d)
        self.assertIn("reviewer", d)

        restored = CuratedDate.from_dict(d)
        self.assertEqual(restored.model, "qwen3-coder")
        self.assertEqual(restored.reviewer, "alice")
        self.assertEqual(restored.extracted_at, original.extracted_at)

    def test_14_authority_candidate_serialization_includes_provenance_fields(self):
        """CORE-ENH-03: AuthorityCandidate roundtrip preserves provenance."""
        original = AuthorityCandidate(
            entry_id="e1",
            source="gnd",
            model="qwen3-coder",
        )
        d = original.to_dict()
        self.assertIn("model", d)
        self.assertIn("extracted_at", d)
        self.assertIn("reviewer", d)

        restored = AuthorityCandidate.from_dict(d)
        self.assertEqual(restored.model, "qwen3-coder")
        self.assertEqual(restored.extracted_at, original.extracted_at)

    def test_15_provenance_values_use_empty_strings_not_none(self):
        """CORE-ENH-03: Missing provenance values are empty strings, not None."""
        cd = CuratedDate(original="1900")
        prov = cd.provenance()
        for key, value in prov.items():
            self.assertIsNotNone(value, f"{key} should not be None")
            self.assertIsInstance(value, str, f"{key} should be a string")


if __name__ == "__main__":
    unittest.main()
