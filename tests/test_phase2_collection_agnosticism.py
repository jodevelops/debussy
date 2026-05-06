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
        # extracted_at not auto-populated (preserves unknown for legacy data)
        self.assertEqual(prov["extracted_at"], "")

    def test_03_authority_candidate_extracted_at_not_auto_populated(self):
        """CORE-ENH-03: AuthorityCandidate.extracted_at not auto-populated (preserves unknown)."""
        cand = AuthorityCandidate(entry_id="e1", source="gnd")
        self.assertEqual(cand.extracted_at, "")
        # Caller should set it explicitly if needed
        cand.extracted_at = "2026-05-06T12:00:00+00:00"
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
        # extracted_at not auto-populated (preserves unknown for legacy data)
        self.assertEqual(prov["extracted_at"], "")

    def test_05_entity_review_extracted_at_not_auto_populated(self):
        """CORE-ENH-03: EntityReview.extracted_at not auto-populated (preserves unknown)."""
        er = EntityReview(text="Test", entity_type="PER")
        self.assertEqual(er.extracted_at, "")
        # Caller should set it explicitly if needed
        er.extracted_at = "2026-05-06T12:00:00+00:00"
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
        # extracted_at not auto-populated (preserves unknown for legacy data)
        self.assertEqual(prov["extracted_at"], "")

    def test_07_curated_date_extracted_at_not_auto_populated(self):
        """CORE-ENH-03: CuratedDate.extracted_at not auto-populated (preserves unknown)."""
        cd = CuratedDate(original="1900", method="rule")
        self.assertEqual(cd.extracted_at, "")
        # Caller should set it explicitly if needed
        cd.extracted_at = "2026-05-06T12:00:00+00:00"
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


class TestIssue120SubjectColumnAgnostic(unittest.TestCase):
    """CORE-ENH-04 (#120): Remove hardcoded subject_extract_original column.

    Previous issue:
    - classify_subjects() had hardcoded default subject_column="subject_extract_original"
    - GIUB-specific column name baked into general analyze module
    - Other collections with different schemas would silently fail
      (return SCHEMA_MISMATCH finding even though they have a subject column)

    Fix:
    - Default is now None, triggering auto-detection
    - infer_subject_column() helper checks common subject column names
      (subject, topic, keywords, schlagwort, etc.)
    - Caller can still pass explicit column name to override
    """

    def setUp(self):
        try:
            import pandas as pd
            self.pd = pd
        except ImportError:
            self.skipTest("pandas required")

    def test_01_infer_subject_column_finds_subject(self):
        """CORE-ENH-04: infer_subject_column finds 'subject' column."""
        from kwb.analyze.semantic import infer_subject_column
        df = self.pd.DataFrame({"id": ["1"], "subject": ["test"]})
        self.assertEqual(infer_subject_column(df), "subject")

    def test_02_infer_subject_column_finds_subject_extract_original(self):
        """CORE-ENH-04: backward compat — finds GIUB-specific column."""
        from kwb.analyze.semantic import infer_subject_column
        df = self.pd.DataFrame({
            "id": ["1"],
            "subject_extract_original": ["test"],
        })
        self.assertEqual(infer_subject_column(df), "subject_extract_original")

    def test_03_infer_subject_column_finds_keywords(self):
        """CORE-ENH-04: infer_subject_column finds 'keywords' column."""
        from kwb.analyze.semantic import infer_subject_column
        df = self.pd.DataFrame({"id": ["1"], "keywords": ["test"]})
        self.assertEqual(infer_subject_column(df), "keywords")

    def test_04_infer_subject_column_finds_german_schlagwort(self):
        """CORE-ENH-04: infer_subject_column finds German 'schlagwort'."""
        from kwb.analyze.semantic import infer_subject_column
        df = self.pd.DataFrame({"id": ["1"], "Schlagwort": ["test"]})
        self.assertEqual(infer_subject_column(df), "Schlagwort")

    def test_05_infer_subject_column_returns_none_when_no_match(self):
        """CORE-ENH-04: infer_subject_column returns None for unmatched schemas."""
        from kwb.analyze.semantic import infer_subject_column
        df = self.pd.DataFrame({"id": ["1"], "name": ["test"]})
        self.assertIsNone(infer_subject_column(df))

    def test_06_infer_subject_column_prefers_specific_over_generic(self):
        """CORE-ENH-04: more specific column names take precedence."""
        from kwb.analyze.semantic import infer_subject_column
        # Both "subject_extract_original" and "subject" present
        df = self.pd.DataFrame({
            "id": ["1"],
            "subject_extract_original": ["a"],
            "subject": ["b"],
        })
        # Specific wins
        self.assertEqual(infer_subject_column(df), "subject_extract_original")

    def test_07_classify_subjects_no_default_column(self):
        """CORE-ENH-04: classify_subjects no longer has hardcoded default."""
        import inspect
        from kwb.analyze.semantic import classify_subjects
        sig = inspect.signature(classify_subjects)
        param = sig.parameters["subject_column"]
        # Default must be None (no hardcoded column name)
        self.assertIsNone(param.default)

    def test_08_classify_subjects_auto_detects_with_no_column_argument(self):
        """CORE-ENH-04: classify_subjects auto-detects subject column."""
        from unittest.mock import MagicMock
        from kwb.analyze.semantic import classify_subjects
        from kwb.core.models import DatasetProfile

        df = self.pd.DataFrame({
            "record_id": ["r1"],
            "subject": ["Minarett"],
        })
        profile = DatasetProfile(
            source_path="test.csv", source_name="test",
            row_count=1, column_count=2, columns=[], id_column="record_id",
        )

        provider = MagicMock()
        provider.complete = MagicMock(return_value=MagicMock(
            content='{"unclassified": [], "classifications": []}',
        ))

        # No subject_column specified — auto-detection should kick in
        findings, batch = classify_subjects(df, profile, provider)
        # Should not produce SCHEMA_MISMATCH for missing subject column,
        # because "subject" is auto-detected
        schema_mismatches = [f for f in findings
                             if "not found" in f.message]
        self.assertEqual(len(schema_mismatches), 0,
                         "Should not report schema mismatch when 'subject' auto-detects")

    def test_09_classify_subjects_reports_when_no_subject_column(self):
        """CORE-ENH-04: classify_subjects reports a finding when no subject column found."""
        from unittest.mock import MagicMock
        from kwb.analyze.semantic import classify_subjects
        from kwb.core.models import DatasetProfile

        df = self.pd.DataFrame({
            "record_id": ["r1"],
            "title": ["Some title"],
        })
        profile = DatasetProfile(
            source_path="test.csv", source_name="test",
            row_count=1, column_count=2, columns=[], id_column="record_id",
        )
        provider = MagicMock()

        findings, _ = classify_subjects(df, profile, provider)
        # Should produce a SCHEMA_MISMATCH finding listing tried candidates
        no_subject = [f for f in findings if "No subject column detected" in f.message]
        self.assertEqual(len(no_subject), 1)

    def test_10_classify_subjects_explicit_column_override(self):
        """CORE-ENH-04: explicit subject_column still takes precedence."""
        from unittest.mock import MagicMock
        from kwb.analyze.semantic import classify_subjects
        from kwb.core.models import DatasetProfile

        df = self.pd.DataFrame({
            "record_id": ["r1"],
            "subject": ["A"],
            "my_custom_topic_field": ["B"],
        })
        profile = DatasetProfile(
            source_path="test.csv", source_name="test",
            row_count=1, column_count=3, columns=[], id_column="record_id",
        )
        provider = MagicMock()
        provider.complete = MagicMock(return_value=MagicMock(
            content='{"unclassified": [], "classifications": []}',
        ))

        # Explicit override
        findings, _ = classify_subjects(
            df, profile, provider, subject_column="my_custom_topic_field",
        )
        # No schema mismatches
        self.assertEqual(len([f for f in findings if "not found" in f.message]), 0)


class TestIssue121NamedEntitySchemaConfigurable(unittest.TestCase):
    """CORE-ENH-05 (#121): Configurable named_entity schema.

    Previous issue:
    - parse_gnd_columns() and flag_low_confidence() hardcoded the
      `named_entity_N_gnd_*` column pattern (GIUB-specific schema)
    - max_entities=11 hardcoded; collections with more or fewer
      entity slots were silently truncated
    - record_id column hardcoded
    - Other GLAM collections couldn't use these functions

    Fix:
    - Added NamedEntitySchema dataclass with configurable column patterns
    - DEFAULT_NAMED_ENTITY_SCHEMA preserves backward compat with GIUB
    - max_entities=None triggers auto-detection from actual columns
    - record_id_column configurable per schema
    """

    def setUp(self):
        try:
            import pandas as pd
            self.pd = pd
        except ImportError:
            self.skipTest("pandas required")

    def test_01_schema_class_exists(self):
        """CORE-ENH-05: NamedEntitySchema dataclass is exported."""
        from kwb.enrich.gnd import NamedEntitySchema
        schema = NamedEntitySchema()
        self.assertIsNotNone(schema)

    def test_02_default_schema_is_giub_compatible(self):
        """CORE-ENH-05: Default schema matches GIUB column names."""
        from kwb.enrich.gnd import DEFAULT_NAMED_ENTITY_SCHEMA
        self.assertEqual(DEFAULT_NAMED_ENTITY_SCHEMA.term_col(1), "named_entity_1")
        self.assertEqual(DEFAULT_NAMED_ENTITY_SCHEMA.id_col(1), "named_entity_1_gnd_id")
        self.assertEqual(
            DEFAULT_NAMED_ENTITY_SCHEMA.preferred_col(1),
            "named_entity_1_gnd_preferredName",
        )
        self.assertEqual(DEFAULT_NAMED_ENTITY_SCHEMA.record_id_column, "record_id")

    def test_03_schema_with_custom_patterns(self):
        """CORE-ENH-05: Custom schema accepts non-GIUB patterns."""
        from kwb.enrich.gnd import NamedEntitySchema
        schema = NamedEntitySchema(
            term_pattern="entity_{n}",
            id_pattern="entity_{n}_authority_id",
            preferred_pattern="entity_{n}_label",
            confidence_pattern="entity_{n}_score",
            type_pattern="entity_{n}_kind",
            alternatives_pattern="entity_{n}_alt_names",
            record_id_column="object_id",
        )
        self.assertEqual(schema.term_col(3), "entity_3")
        self.assertEqual(schema.id_col(3), "entity_3_authority_id")
        self.assertEqual(schema.confidence_col(3), "entity_3_score")
        self.assertEqual(schema.record_id_column, "object_id")

    def test_04_detect_max_entities_auto_detects(self):
        """CORE-ENH-05: detect_max_entities counts existing slots."""
        from kwb.enrich.gnd import DEFAULT_NAMED_ENTITY_SCHEMA
        df = self.pd.DataFrame({
            "record_id": ["r1"],
            "named_entity_1_gnd_id": ["gnd:1"],
            "named_entity_2_gnd_id": ["gnd:2"],
            "named_entity_3_gnd_id": ["gnd:3"],
        })
        self.assertEqual(DEFAULT_NAMED_ENTITY_SCHEMA.detect_max_entities(df), 3)

    def test_05_detect_max_entities_returns_zero_for_no_match(self):
        """CORE-ENH-05: detect_max_entities returns 0 when no entity columns."""
        from kwb.enrich.gnd import DEFAULT_NAMED_ENTITY_SCHEMA
        df = self.pd.DataFrame({"record_id": ["r1"], "title": ["foo"]})
        self.assertEqual(DEFAULT_NAMED_ENTITY_SCHEMA.detect_max_entities(df), 0)

    def test_06_parse_gnd_columns_no_hardcoded_max(self):
        """CORE-ENH-05: parse_gnd_columns max_entities defaults to None (auto)."""
        import inspect
        from kwb.enrich.gnd import parse_gnd_columns
        sig = inspect.signature(parse_gnd_columns)
        param = sig.parameters["max_entities"]
        self.assertIsNone(param.default)

    def test_07_parse_gnd_columns_auto_detects_max(self):
        """CORE-ENH-05: parse_gnd_columns auto-detects max_entities."""
        from kwb.enrich.gnd import parse_gnd_columns
        df = self.pd.DataFrame({
            "record_id": ["r1"],
            "named_entity_1": ["Berlin"],
            "named_entity_1_gnd_id": ["4005765-8"],
            "named_entity_1_gnd_preferredName": ["Berlin"],
            "named_entity_1_gnd_konfidenz": ["95%"],
            "named_entity_1_gnd_type": ["PlaceOrGeographicName"],
            "named_entity_1_gnd_alternativen": [""],
        })
        # Should still find Berlin even though we don't pass max_entities
        matches = parse_gnd_columns(df)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].gnd_id, "4005765-8")

    def test_08_parse_gnd_columns_with_custom_schema(self):
        """CORE-ENH-05: parse_gnd_columns works with custom column schema."""
        from kwb.enrich.gnd import NamedEntitySchema, parse_gnd_columns

        custom_schema = NamedEntitySchema(
            term_pattern="entity_{n}",
            id_pattern="entity_{n}_id",
            preferred_pattern="entity_{n}_name",
            confidence_pattern="entity_{n}_score",
            type_pattern="entity_{n}_type",
            alternatives_pattern="entity_{n}_alt",
            record_id_column="obj_id",
        )

        df = self.pd.DataFrame({
            "obj_id": ["o1"],
            "entity_1": ["Munich"],
            "entity_1_id": ["4039964-3"],
            "entity_1_name": ["München"],
            "entity_1_score": ["88%"],
            "entity_1_type": ["PlaceOrGeographicName"],
            "entity_1_alt": [""],
        })

        matches = parse_gnd_columns(df, schema=custom_schema)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].gnd_id, "4039964-3")
        self.assertEqual(matches[0].record_id, "o1")

    def test_09_flag_low_confidence_no_hardcoded_max(self):
        """CORE-ENH-05: flag_low_confidence max_entities defaults to None."""
        import inspect
        from kwb.enrich.gnd import flag_low_confidence
        sig = inspect.signature(flag_low_confidence)
        self.assertIsNone(sig.parameters["max_entities"].default)

    def test_10_flag_low_confidence_with_custom_schema(self):
        """CORE-ENH-05: flag_low_confidence works with custom schema."""
        from kwb.enrich.gnd import NamedEntitySchema, flag_low_confidence

        custom_schema = NamedEntitySchema(
            id_pattern="ent_{n}_authority",
            confidence_pattern="ent_{n}_conf",
            term_pattern="ent_{n}_text",
            record_id_column="rec_id",
        )

        df = self.pd.DataFrame({
            "rec_id": ["r1"],
            "ent_1_text": ["Munich"],
            "ent_1_authority": ["12345"],
            "ent_1_conf": ["50%"],  # Low confidence
        })

        flags = flag_low_confidence(df, threshold=0.75, schema=custom_schema)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["record_id"], "r1")
        self.assertEqual(flags[0]["term"], "Munich")
        self.assertEqual(flags[0]["confidence"], 0.5)

    def test_11_parse_gnd_columns_handles_no_entity_columns(self):
        """CORE-ENH-05: parse_gnd_columns returns empty list when no schema cols."""
        from kwb.enrich.gnd import parse_gnd_columns
        df = self.pd.DataFrame({"record_id": ["r1"], "title": ["foo"]})
        matches = parse_gnd_columns(df)
        self.assertEqual(matches, [])


class TestIssue136MultilingualWikidata(unittest.TestCase):
    """CORE-ENH-06 (#136): Multilingual Wikidata support.

    Previous issue:
    - SPARQL queries had hardcoded `FILTER(LANG(?typeLabel) = "de")`
    - Even when caller passed lang="en", the type label was filtered
      for German only, returning empty type labels in non-DE searches
    - No central control of default language via env var

    Fix:
    - FILTER now uses the {lang} parameter dynamically
    - Added DEFAULT_LANG module-level constant configurable via
      DEBUSSY_WIKIDATA_LANG env var
    - All public functions accept lang=None (uses DEFAULT_LANG)
    - lang param can be overridden per-call
    """

    def test_01_default_lang_constant_exists(self):
        """CORE-ENH-06: DEFAULT_LANG constant is exported."""
        from kwb.enrich.wikidata import DEFAULT_LANG
        self.assertIsInstance(DEFAULT_LANG, str)
        self.assertGreater(len(DEFAULT_LANG), 0)

    def test_02_default_lang_reads_from_env(self):
        """CORE-ENH-06: DEFAULT_LANG reads DEBUSSY_WIKIDATA_LANG env var."""
        import os
        import importlib
        # Set env var before reimport
        original = os.environ.get("DEBUSSY_WIKIDATA_LANG")
        try:
            os.environ["DEBUSSY_WIKIDATA_LANG"] = "fr"
            import kwb.enrich.wikidata as wikidata_mod
            importlib.reload(wikidata_mod)
            self.assertEqual(wikidata_mod.DEFAULT_LANG, "fr")
        finally:
            if original is None:
                os.environ.pop("DEBUSSY_WIKIDATA_LANG", None)
            else:
                os.environ["DEBUSSY_WIKIDATA_LANG"] = original
            # Restore original module state
            import kwb.enrich.wikidata as wikidata_mod
            importlib.reload(wikidata_mod)

    def test_03_search_query_no_hardcoded_german(self):
        """CORE-ENH-06: SPARQL search query uses {lang} not hardcoded 'de'."""
        from kwb.enrich.wikidata import _sparql_search_query
        query_en = _sparql_search_query("Berlin", lang="en")
        # Hardcoded German FILTER must be gone
        self.assertNotIn('FILTER(LANG(?typeLabel) = "de")', query_en)
        # English filter should be present instead
        self.assertIn('FILTER(LANG(?typeLabel) = "en")', query_en)

    def test_04_search_query_propagates_lang_to_filter(self):
        """CORE-ENH-06: lang parameter flows into typeLabel filter."""
        from kwb.enrich.wikidata import _sparql_search_query
        for lang in ("de", "en", "fr", "it"):
            query = _sparql_search_query("test", lang=lang)
            self.assertIn(f'FILTER(LANG(?typeLabel) = "{lang}")', query)

    def test_05_search_query_lang_none_uses_default(self):
        """CORE-ENH-06: lang=None falls back to DEFAULT_LANG."""
        from kwb.enrich.wikidata import _sparql_search_query, DEFAULT_LANG
        query = _sparql_search_query("test", lang=None)
        self.assertIn(f'FILTER(LANG(?typeLabel) = "{DEFAULT_LANG}")', query)

    def test_06_person_query_lang_configurable(self):
        """CORE-ENH-06: _sparql_person_query accepts lang parameter."""
        from kwb.enrich.wikidata import _sparql_person_query
        query_en = _sparql_person_query("Goethe", lang="en")
        self.assertIn('mwapi:language "en"', query_en)
        self.assertIn('wikibase:language "en,en"', query_en)

    def test_07_place_query_lang_configurable(self):
        """CORE-ENH-06: _sparql_place_query accepts lang parameter."""
        from kwb.enrich.wikidata import _sparql_place_query
        query_fr = _sparql_place_query("Paris", lang="fr")
        self.assertIn('mwapi:language "fr"', query_fr)

    def test_08_wikidata_search_lang_default_is_none(self):
        """CORE-ENH-06: wikidata_search uses lang=None to indicate default."""
        import inspect
        from kwb.enrich.wikidata import wikidata_search
        sig = inspect.signature(wikidata_search)
        self.assertIsNone(sig.parameters["lang"].default)

    def test_09_wikidata_batch_search_lang_default_is_none(self):
        """CORE-ENH-06: wikidata_batch_search uses lang=None to indicate default."""
        import inspect
        from kwb.enrich.wikidata import wikidata_batch_search
        sig = inspect.signature(wikidata_batch_search)
        self.assertIsNone(sig.parameters["lang"].default)

    def test_10_label_service_includes_english_fallback(self):
        """CORE-ENH-06: SPARQL label service always falls back to English."""
        from kwb.enrich.wikidata import _sparql_search_query
        # German default
        query_de = _sparql_search_query("test", lang="de")
        self.assertIn('"de,en"', query_de)
        # French requested
        query_fr = _sparql_search_query("test", lang="fr")
        self.assertIn('"fr,en"', query_fr)


if __name__ == "__main__":
    unittest.main()
