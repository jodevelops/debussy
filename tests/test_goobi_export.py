"""
Tests for export/goobi_xml.py.

Strategy:
- Parse generated XML with stdlib xml.etree.ElementTree.
- Assert element presence, attributes, text content.
- Test person name splitting, repeatable fields, GND authority injection.
- Test that empty workspace mapping raises ValueError.
- Test real-world scenario from sample1_goobi.xml structure.
- Test batch export produces one <goobi-import> per record.
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kwb.core.workspace import (
    Workspace, FieldMapping, GoobiMetadataType, DictionaryEntry,
)
from kwb.export.goobi_xml import (
    record_to_xml, dataframe_to_goobi_xml,
    _parse_name, _split_repeatable,
    _et_indent,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _to_str(elem) -> str:
    from xml.etree.ElementTree import tostring
    _et_indent(elem)
    return tostring(elem, encoding="unicode")


def _ws_basic() -> Workspace:
    ws = Workspace.create("Test")
    ws.set_field_mapping([
        FieldMapping("record_id", "CatalogIDDigital", label="Identifier"),
        FieldMapping("title",     "TitleDocMain",     label="Titel"),
        FieldMapping("year",      "PublicationYear",  label="Jahr"),
        FieldMapping("desc",      "Description",      label="Beschreibung"),
    ])
    return ws


# ---------------------------------------------------------------------------
# _parse_name
# ---------------------------------------------------------------------------

class TestParseName(unittest.TestCase):

    def test_lastname_firstname(self):
        fn, ln = _parse_name("Müller, Peter")
        self.assertEqual(fn, "Peter")
        self.assertEqual(ln, "Müller")

    def test_firstname_lastname(self):
        fn, ln = _parse_name("Peter Müller")
        self.assertEqual(fn, "Peter")
        self.assertEqual(ln, "Müller")

    def test_single_name(self):
        fn, ln = _parse_name("Rembrandt")
        self.assertEqual(fn, "")
        self.assertEqual(ln, "Rembrandt")

    def test_multiple_first_names(self):
        fn, ln = _parse_name("Johann Sebastian Bach")
        # Last word → lastname
        self.assertEqual(ln, "Bach")


class TestSplitRepeatable(unittest.TestCase):

    def test_single_value(self):
        self.assertEqual(_split_repeatable("Physik"), ["Physik"])

    def test_semicolon_separated(self):
        self.assertEqual(
            _split_repeatable("Physik; Chemie; Biologie"),
            ["Physik", "Chemie", "Biologie"],
        )

    def test_strips_whitespace(self):
        self.assertEqual(
            _split_repeatable("  Physik  ;  Chemie  "),
            ["Physik", "Chemie"],
        )

    def test_empty_parts_ignored(self):
        self.assertEqual(_split_repeatable("A;;B"), ["A", "B"])


# ---------------------------------------------------------------------------
# record_to_xml
# ---------------------------------------------------------------------------

class TestRecordToXml(unittest.TestCase):

    def _basic_row(self):
        return {
            "record_id": "obj_199",
            "title": "Mein Titel",
            "year": "2011",
            "desc": "Eine Beschreibung.",
        }

    def _basic_mappings(self):
        return [
            FieldMapping("record_id", "CatalogIDDigital", label="Identifier"),
            FieldMapping("title", "TitleDocMain", label="Titel"),
            FieldMapping("year", "PublicationYear", label="Jahr"),
            FieldMapping("desc", "Description", label="Beschreibung"),
        ]

    def test_root_element_is_goobi_import(self):
        elem = record_to_xml(self._basic_row(), self._basic_mappings())
        self.assertEqual(elem.tag, "goobi-import")

    def test_data_element_has_type(self):
        elem = record_to_xml(self._basic_row(), self._basic_mappings(), doc_type="MuseumObject")
        data = elem.find("data")
        self.assertEqual(data.get("type"), "MuseumObject")

    def test_metadata_text_content(self):
        elem = record_to_xml(self._basic_row(), self._basic_mappings())
        titles = elem.findall(".//metadata[@type='TitleDocMain']")
        self.assertEqual(len(titles), 1)
        self.assertEqual(titles[0].text, "Mein Titel")

    def test_metadata_label_attribute(self):
        elem = record_to_xml(self._basic_row(), self._basic_mappings())
        meta = elem.find(".//metadata[@type='TitleDocMain']")
        self.assertEqual(meta.get("label"), "Titel")

    def test_process_title_is_record_id(self):
        elem = record_to_xml(self._basic_row(), self._basic_mappings())
        title = elem.find(".//process/title")
        self.assertEqual(title.text, "obj_199")

    def test_journal_element_present(self):
        elem = record_to_xml(self._basic_row(), self._basic_mappings())
        journal = elem.find(".//journal")
        self.assertIsNotNone(journal)
        self.assertEqual(journal.get("type"), "info")

    def test_missing_value_skipped(self):
        row = self._basic_row()
        row["title"] = ""
        elem = record_to_xml(row, self._basic_mappings())
        titles = elem.findall(".//metadata[@type='TitleDocMain']")
        self.assertEqual(len(titles), 0)

    def test_nan_value_skipped(self):
        row = self._basic_row()
        row["year"] = float("nan")
        elem = record_to_xml(row, self._basic_mappings())
        years = elem.findall(".//metadata[@type='PublicationYear']")
        self.assertEqual(len(years), 0)

    def test_ignored_mapping_excluded(self):
        mappings = [
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("internal_notes", GoobiMetadataType.IGNORE.value, enabled=True),
        ]
        row = {"record_id": "r1", "internal_notes": "secret"}
        elem = record_to_xml(row, mappings)
        # No metadata for internal_notes
        self.assertEqual(elem.find(".//metadata[@type='__ignore__']"), None)

    def test_disabled_mapping_excluded(self):
        mappings = [
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("title", "TitleDocMain", enabled=False),
        ]
        row = {"record_id": "r1", "title": "Shown"}
        elem = record_to_xml(row, mappings)
        titles = elem.findall(".//metadata[@type='TitleDocMain']")
        self.assertEqual(len(titles), 0)


class TestRecordToXmlGND(unittest.TestCase):

    def test_gnd_authority_from_dictionary(self):
        dictionary = {
            "berlin": DictionaryEntry(
                term="Berlin", gnd_id="4005765-8",
                gnd_type="PlaceOrGeographicName",
            )
        }
        mappings = [FieldMapping("place", "SubjectGeographic", label="Ort")]
        row = {"record_id": "r1", "place": "Berlin"}
        elem = record_to_xml(row, mappings, dictionary=dictionary)
        meta = elem.find(".//metadata[@type='SubjectGeographic']")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.get("authority"), "gnd")
        self.assertEqual(meta.get("valueURI"), "4005765-8")
        self.assertEqual(meta.get("authorityURI"), "http://d-nb.info/gnd/")

    def test_no_gnd_when_not_in_dictionary(self):
        mappings = [FieldMapping("place", "SubjectGeographic")]
        row = {"record_id": "r1", "place": "Unbekannt"}
        elem = record_to_xml(row, mappings, dictionary={})
        meta = elem.find(".//metadata[@type='SubjectGeographic']")
        self.assertIsNone(meta.get("authority"))


class TestRecordToXmlRepeatable(unittest.TestCase):

    def test_repeatable_field_expands_to_multiple_elements(self):
        mappings = [
            FieldMapping("collection", "singleDigCollection",
                         label="Sammlung", repeatable=True),
        ]
        row = {"record_id": "r1", "collection": "Physik; Chemie; Biologie"}
        elem = record_to_xml(row, mappings)
        colls = elem.findall(".//metadata[@type='singleDigCollection']")
        self.assertEqual(len(colls), 3)
        texts = {c.text for c in colls}
        self.assertEqual(texts, {"Physik", "Chemie", "Biologie"})

    def test_collection_type_auto_repeatable(self):
        """singleDigCollection is repeatable even without repeatable=True."""
        mappings = [
            FieldMapping("collection", "singleDigCollection", label="Sammlung"),
        ]
        row = {"record_id": "r1", "collection": "A; B"}
        elem = record_to_xml(row, mappings)
        colls = elem.findall(".//metadata[@type='singleDigCollection']")
        self.assertEqual(len(colls), 2)


class TestRecordToXmlPerson(unittest.TestCase):

    def test_person_element_created(self):
        mappings = [FieldMapping("author", "Author", label="Autor")]
        row = {"record_id": "r1", "author": "Müller, Peter"}
        elem = record_to_xml(row, mappings)
        persons = elem.findall(".//person[@role='Author']")
        self.assertEqual(len(persons), 1)
        self.assertEqual(persons[0].get("lastname"), "Müller")
        self.assertEqual(persons[0].get("firstname"), "Peter")

    def test_repeatable_persons(self):
        mappings = [FieldMapping("authors", "Author", label="Autor", repeatable=True)]
        row = {"record_id": "r1", "authors": "Müller, Peter; Schmidt, Anna"}
        elem = record_to_xml(row, mappings)
        persons = elem.findall(".//person[@role='Author']")
        self.assertEqual(len(persons), 2)


# ---------------------------------------------------------------------------
# dataframe_to_goobi_xml: batch export
# ---------------------------------------------------------------------------

class TestDataframeToGoobiXml(unittest.TestCase):

    def _df_and_ws(self):
        df = pd.DataFrame([
            {"record_id": "obj_001", "title": "Titel A", "year": "1920"},
            {"record_id": "obj_002", "title": "Titel B", "year": "1935"},
        ])
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("title", "TitleDocMain"),
            FieldMapping("year", "PublicationYear"),
        ])
        return df, ws

    def test_output_is_string(self):
        df, ws = self._df_and_ws()
        xml_str = dataframe_to_goobi_xml(df, ws)
        self.assertIsInstance(xml_str, str)

    def test_has_xml_declaration(self):
        df, ws = self._df_and_ws()
        xml_str = dataframe_to_goobi_xml(df, ws)
        self.assertTrue(xml_str.startswith('<?xml'))

    def test_batch_wrapper(self):
        df, ws = self._df_and_ws()
        xml_str = dataframe_to_goobi_xml(df, ws)
        self.assertIn("<goobi-batch>", xml_str)
        self.assertIn("</goobi-batch>", xml_str)

    def test_two_records_two_imports(self):
        df, ws = self._df_and_ws()
        xml_str = dataframe_to_goobi_xml(df, ws)
        count = xml_str.count("<goobi-import>")
        self.assertEqual(count, 2)

    def test_record_ids_in_output(self):
        df, ws = self._df_and_ws()
        xml_str = dataframe_to_goobi_xml(df, ws)
        self.assertIn("obj_001", xml_str)
        self.assertIn("obj_002", xml_str)

    def test_empty_mapping_raises(self):
        df = pd.DataFrame([{"record_id": "r1"}])
        ws = Workspace.create("Empty")
        # No mappings set
        with self.assertRaises(ValueError):
            dataframe_to_goobi_xml(df, ws)

    def test_all_disabled_mapping_raises(self):
        df = pd.DataFrame([{"record_id": "r1"}])
        ws = Workspace.create("Empty")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital", enabled=False)
        ])
        with self.assertRaises(ValueError):
            dataframe_to_goobi_xml(df, ws)

    def test_sample_goobi_structure(self):
        """Reproduce the structure from sample1_goobi.xml."""
        df = pd.DataFrame([{
            "record_id": "obj_199",
            "title": "Mein Titel",
            "year": "2011",
            "desc": "Die vorliegende Arbeit...",
            "lang": "ger",
            "collection": "Wissenschaftliche Sammlungen; Architektur; Physik",
        }])
        ws = Workspace.create("GIUB")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital", label="Identifier"),
            FieldMapping("title",  "TitleDocMain",       label="Titel"),
            FieldMapping("year",   "PublicationYear",    label="Erscheinungsjahr"),
            FieldMapping("desc",   "Description",        label="Beschreibung"),
            FieldMapping("lang",   "DocLanguage",        label="Language"),
            FieldMapping("collection", "singleDigCollection", label="Sammlung"),
        ])
        xml_str = dataframe_to_goobi_xml(df, ws)
        # Three collections
        self.assertEqual(xml_str.count("singleDigCollection"), 3)
        self.assertIn("Wissenschaftliche Sammlungen", xml_str)
        self.assertIn("Architektur", xml_str)
        self.assertIn("Physik", xml_str)
        self.assertIn("obj_199", xml_str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
