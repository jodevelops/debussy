"""
Phase 2: Collection-Agnosticism Regression Tests

Tests for audit issues #103, #110, #120, #121, #136.
Each test is annotated with the audit ID it addresses.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kwb.core.workspace import Workspace, FieldMapping


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


if __name__ == "__main__":
    unittest.main()
