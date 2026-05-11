"""
Tests for export/mets_mods.py.

Strategy:
- Parse generated METS/MODS XML with stdlib xml.etree.ElementTree.
- Assert METS structure (metsHdr, dmdSec, fileSec, structMap).
- Assert MODS elements (titleInfo, name, subject, identifier).
- Test NER entity mapping to MODS subjects (geographic, name).
- Test EDTF date encoding in temporal elements.
- Test GND authority references in names and subjects.
- Test batch export produces one dmdSec per record.
"""

import sys
import unittest
from pathlib import Path
from xml.etree.ElementTree import fromstring

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kwb.core.workspace import (
    Workspace, FieldMapping, EntityReview, ReviewStatus, CuratedDate,
)
from kwb.export.mets_mods import export_mets_mods


# Constants for XML namespace handling
_METS_NS = "http://www.loc.gov/METS/"
_MODS_NS = "http://www.loc.gov/mods/v3"
_XLINK_NS = "http://www.w3.org/1999/xlink"


def _find_elements(root, tag_local: str, ns: str = "") -> list:
    """Find all elements by local tag name, optionally with namespace."""
    if ns:
        full_tag = f"{{{ns}}}{tag_local}"
    else:
        full_tag = tag_local
    return root.findall(f".//{full_tag}")


def _ws_basic() -> Workspace:
    """Create a workspace with basic field mapping."""
    ws = Workspace.create("Test")
    ws.set_field_mapping([
        FieldMapping("record_id", "CatalogIDDigital", label="Identifier"),
        FieldMapping("title", "TitleDocMain", label="Titel"),
        FieldMapping("creator", "Creator", label="Schöpfer"),
        FieldMapping("date", "DateCreated", label="Datierung"),
        FieldMapping("subject", "SubjectTopic", label="Thema"),
        FieldMapping("place", "SubjectGeographic", label="Ort"),
    ])
    return ws


class TestMetsStructure(unittest.TestCase):
    """Test basic METS XML structure."""

    def test_root_element_is_mets(self):
        """Root element must be <mets> with correct namespaces."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test Record"],
        })
        mets_str = export_mets_mods(df, ws)
        self.assertIn('<?xml version="1.0"', mets_str)
        root = fromstring(mets_str)
        self.assertEqual(root.tag, f"{{{_METS_NS}}}mets")
        # Namespace declarations are in the XML but not as regular attributes
        self.assertIn("xmlns:mets", mets_str)
        self.assertIn("xmlns:mods", mets_str)

    def test_mets_header_present(self):
        """METS document must have metsHdr."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test Record"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        headers = _find_elements(root, "metsHdr", _METS_NS)
        self.assertEqual(len(headers), 1)
        self.assertEqual(headers[0].get("RECORDSTATUS"), "Complete")

    def test_dmd_sec_per_record(self):
        """Each record gets one dmdSec with MODS content."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001", "rec-002"],
            "title": ["Title 1", "Title 2"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        dmd_secs = _find_elements(root, "dmdSec", _METS_NS)
        self.assertEqual(len(dmd_secs), 2)

    def test_file_section_present(self):
        """fileSec with fileGrp is present."""
        ws = _ws_basic()
        df = pd.DataFrame({"record_id": ["rec-001"]})
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        file_secs = _find_elements(root, "fileSec", _METS_NS)
        self.assertEqual(len(file_secs), 1)

    def test_struct_map_present(self):
        """structMap maps records to dmdSec references."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001", "rec-002"],
            "title": ["Title 1", "Title 2"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        struct_maps = _find_elements(root, "structMap", _METS_NS)
        self.assertEqual(len(struct_maps), 1)
        # Should have divs per record
        divs = _find_elements(struct_maps[0], "div", _METS_NS)
        self.assertGreater(len(divs), 2)  # root div + record divs


class TestModsContent(unittest.TestCase):
    """Test MODS metadata element generation."""

    def test_title_mapping(self):
        """TitleDocMain field maps to MODS titleInfo/title."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["My Document Title"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        titles = _find_elements(root, "title", _MODS_NS)
        self.assertGreater(len(titles), 0)
        self.assertEqual(titles[0].text, "My Document Title")

    def test_creator_mapping(self):
        """Creator field maps to MODS name element."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "creator": ["Johann Wolfgang von Goethe"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        names = _find_elements(root, "name", _MODS_NS)
        self.assertGreater(len(names), 0)

    def test_date_mapping(self):
        """DateCreated field maps to MODS dateIssued."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "date": ["1920"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        dates = _find_elements(root, "dateIssued", _MODS_NS)
        self.assertGreater(len(dates), 0)
        self.assertEqual(dates[0].text, "1920")

    def test_subject_mapping(self):
        """SubjectTopic field maps to MODS subject/topic."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "subject": ["Kartographie; Geographie"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        topics = _find_elements(root, "topic", _MODS_NS)
        self.assertGreater(len(topics), 0)

    def test_identifier_mapping(self):
        """CatalogIDDigital maps to MODS identifier."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-123"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        idents = _find_elements(root, "identifier", _MODS_NS)
        # Should have at least one identifier element
        self.assertGreater(len(idents), 0)


class TestNerEntityMapping(unittest.TestCase):
    """Test NER entity inclusion in MODS subjects."""

    def test_place_entities_as_geographic(self):
        """LOC/GPE entities map to MODS subject/geographic."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test"],
        })

        # Add place entity
        er = EntityReview(
            entity_type="LOC",
            text="Alpen",
            record_id="rec-001",
            status=ReviewStatus.ACCEPTED,
        )
        ws.entity_reviews.append(er)

        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        geogs = _find_elements(root, "geographic", _MODS_NS)
        self.assertGreater(len(geogs), 0)
        found = any(g.text == "Alpen" for g in geogs)
        self.assertTrue(found, "Place entity should appear in geographic subject")

    def test_person_entities_as_names(self):
        """PER entities map to MODS name elements."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test"],
        })

        # Add person entity
        er = EntityReview(
            entity_type="PER",
            text="Goethe",
            record_id="rec-001",
            status=ReviewStatus.ACCEPTED,
        )
        ws.entity_reviews.append(er)

        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        names = _find_elements(root, "name", _MODS_NS)
        # Should have person entities as names
        self.assertGreater(len(names), 0)

    def test_gnd_authority_on_person(self):
        """GND ID on person entity becomes MODS name authority attribute."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test"],
        })

        # Add person entity with GND ID
        er = EntityReview(
            entity_type="PER",
            text="Goethe",
            gnd_id="118540238",
            record_id="rec-001",
            status=ReviewStatus.ACCEPTED,
        )
        ws.entity_reviews.append(er)

        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        names = _find_elements(root, "name", _MODS_NS)
        # At least one should have GND authority
        gnd_names = [n for n in names if n.get("authority") == "gnd"]
        self.assertGreater(len(gnd_names), 0)

    def test_gnd_authority_on_place(self):
        """GND ID on place entity becomes MODS subject authority attribute."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test"],
        })

        # Add place entity with GND ID
        er = EntityReview(
            entity_type="LOC",
            text="Berlin",
            gnd_id="4005728-7",
            record_id="rec-001",
            status=ReviewStatus.ACCEPTED,
        )
        ws.entity_reviews.append(er)

        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        subjects = _find_elements(root, "subject", _MODS_NS)
        gnd_subjects = [s for s in subjects if s.get("authority") == "gnd"]
        self.assertGreater(len(gnd_subjects), 0)


class TestEdtfDates(unittest.TestCase):
    """Test EDTF date normalization in MODS temporal elements."""

    def test_edtf_date_in_subject_temporal(self):
        """EDTF-normalized dates appear in MODS subject/temporal."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test"],
        })

        # Add EDTF date
        cd = CuratedDate(
            column="date_col",
            original="ca. 1920",
            edtf="1920~",
            record_id="rec-001",
        )
        ws.dates.append(cd)

        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        temporals = _find_elements(root, "temporal", _MODS_NS)
        self.assertGreater(len(temporals), 0)
        found = any(t.text == "1920~" for t in temporals)
        self.assertTrue(found, "EDTF date should appear in temporal element")

    def test_edtf_encoding_attribute(self):
        """EDTF temporal element has encoding='edtf' attribute."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test"],
        })

        cd = CuratedDate(
            column="date_col",
            original="1920-1930",
            edtf="1920/1930",
            record_id="rec-001",
        )
        ws.dates.append(cd)

        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        temporals = _find_elements(root, "temporal", _MODS_NS)
        edtf_temporals = [t for t in temporals if t.get("encoding") == "edtf"]
        self.assertGreater(len(edtf_temporals), 0)


class TestBatchExport(unittest.TestCase):
    """Test batch export with multiple records."""

    def test_multiple_records_have_separate_dmdsecs(self):
        """Batch export creates one dmdSec per record."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001", "rec-002", "rec-003"],
            "title": ["Title 1", "Title 2", "Title 3"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        dmd_secs = _find_elements(root, "dmdSec", _METS_NS)
        self.assertEqual(len(dmd_secs), 3)

    def test_batch_export_respects_limit(self):
        """Batch export limit parameter caps records."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": [f"rec-{i:03d}" for i in range(100)],
            "title": [f"Title {i}" for i in range(100)],
        })
        mets_str = export_mets_mods(df, ws, limit=10)
        root = fromstring(mets_str)
        dmd_secs = _find_elements(root, "dmdSec", _METS_NS)
        self.assertEqual(len(dmd_secs), 10)

    def test_struct_map_divs_match_records(self):
        """structMap divs correspond to exported records."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001", "rec-002"],
            "title": ["Title 1", "Title 2"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        struct_maps = _find_elements(root, "structMap", _METS_NS)
        divs = _find_elements(struct_maps[0], "div", _METS_NS)
        # Should have root div + 2 record divs
        record_divs = [d for d in divs if d.get("TYPE") == "record"]
        self.assertEqual(len(record_divs), 2)


class TestEmptyAndNull(unittest.TestCase):
    """Test handling of empty and null values."""

    def test_null_columns_ignored(self):
        """NaN/None columns are not added to MODS."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test"],
            "creator": [None],
            "subject": [pd.NA],
        })
        mets_str = export_mets_mods(df, ws)
        # Should not raise; null values ignored
        root = fromstring(mets_str)
        self.assertIsNotNone(root)

    def test_empty_workspace_produces_valid_xml(self):
        """METS export works with empty workspace (no enrichments)."""
        ws = Workspace.create("Empty")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital"),
        ])
        df = pd.DataFrame({"record_id": ["rec-001"]})
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)
        self.assertEqual(root.tag, f"{{{_METS_NS}}}mets")


if __name__ == "__main__":
    unittest.main()
