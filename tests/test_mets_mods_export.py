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
    ImageAnalysisResult, ImageReviewStatus,
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


class TestCodexReview(unittest.TestCase):
    """Regression tests for Codex review feedback on PR #205."""

    def test_subject_geographic_uses_geographic_element(self):
        """SubjectGeographic field maps to mods:geographic, not mods:topic."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("place", "SubjectGeographic", label="Ort"),
        ])
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "place": ["Berlin"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        # Should produce <subject><geographic>Berlin</geographic></subject>
        geos = _find_elements(root, "geographic", _MODS_NS)
        geo_texts = [g.text for g in geos]
        self.assertIn("Berlin", geo_texts,
                      "SubjectGeographic must map to mods:geographic")

        # And NOT to <topic>
        topics = _find_elements(root, "topic", _MODS_NS)
        topic_texts = [t.text for t in topics]
        self.assertNotIn("Berlin", topic_texts,
                         "SubjectGeographic must NOT map to mods:topic")

    def test_subject_person_uses_name_personal(self):
        """SubjectPerson field maps to mods:name[@type=personal]/namePart."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("person", "SubjectPerson", label="Person"),
        ])
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "person": ["Albert Einstein"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        # Find subject > name > namePart
        subjects = _find_elements(root, "subject", _MODS_NS)
        found = False
        for subj in subjects:
            names = subj.findall(f"{{{_MODS_NS}}}name")
            for name in names:
                if name.get("type") == "personal":
                    parts = name.findall(f"{{{_MODS_NS}}}namePart")
                    for p in parts:
                        if p.text == "Albert Einstein":
                            found = True
        self.assertTrue(found, "SubjectPerson must map to <subject><name type='personal'><namePart>")

    def test_subject_topic_still_uses_topic(self):
        """SubjectTopic (regular subject) still maps to mods:topic."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("subject", "SubjectTopic", label="Thema"),
        ])
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "subject": ["Kartographie"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        topics = _find_elements(root, "topic", _MODS_NS)
        topic_texts = [t.text for t in topics]
        self.assertIn("Kartographie", topic_texts,
                      "SubjectTopic must map to mods:topic")

    def test_place_without_gnd_has_no_authority_attribute(self):
        """LOC entities without a GND ID must NOT have authority='gnd' on subject."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test"],
        })

        # Place entity WITHOUT GND ID
        er = EntityReview(
            entity_type="LOC",
            text="UnknownPlace",
            record_id="rec-001",
            status=ReviewStatus.ACCEPTED,
        )
        ws.entity_reviews.append(er)

        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        # Find the subject that contains "UnknownPlace"
        subjects = _find_elements(root, "subject", _MODS_NS)
        for subj in subjects:
            geos = subj.findall(f"{{{_MODS_NS}}}geographic")
            for g in geos:
                if g.text == "UnknownPlace":
                    self.assertIsNone(
                        subj.get("authority"),
                        "Unlinked place must not have authority='gnd'"
                    )
                    self.assertIsNone(
                        subj.get("valueURI"),
                        "Unlinked place must not have valueURI"
                    )

    def test_place_with_gnd_has_authority_attribute(self):
        """LOC entities with GND ID still get authority='gnd' (no regression)."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test"],
        })

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

        # At least one subject should have authority="gnd"
        subjects = _find_elements(root, "subject", _MODS_NS)
        gnd_subjects = [s for s in subjects if s.get("authority") == "gnd"]
        self.assertGreater(len(gnd_subjects), 0,
                           "Linked place must have authority='gnd'")

    def test_image_mapped_field_appears_in_mods(self):
        """Accepted image.* field mapping must surface in MODS output (P1)."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("image.description", "Description", label="Bildbeschreibung"),
        ])
        df = pd.DataFrame({
            "record_id": ["rec-001"],
        })

        # Add accepted image analysis with description
        img = ImageAnalysisResult(
            image_id="img-001",
            filename="test.jpg",
            record_id="rec-001",
            review_status=ImageReviewStatus.ACCEPTED,
            result={"description": "A historical map of the Alps."},
        )
        ws.image_analyses.append(img)

        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        # The description should appear as mods:abstract
        abstracts = _find_elements(root, "abstract", _MODS_NS)
        abstract_texts = [a.text for a in abstracts]
        self.assertIn("A historical map of the Alps.", abstract_texts,
                      "image.description must surface in MODS when mapped to Description")

    def test_creator_role_uses_roleterm_child(self):
        """MODS role element must wrap role value in <roleTerm> per schema (P1)."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("creator", "Creator", label="Schöpfer"),
        ])
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "creator": ["Albert Einstein"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        names = _find_elements(root, "name", _MODS_NS)
        found_role_term = False
        for name_el in names:
            roles = name_el.findall(f"{{{_MODS_NS}}}role")
            for role_el in roles:
                # role MUST contain roleTerm children, not be a text-only element
                role_terms = role_el.findall(f"{{{_MODS_NS}}}roleTerm")
                if role_terms:
                    found_role_term = True
                    for rt in role_terms:
                        self.assertIsNotNone(
                            rt.get("type"),
                            "roleTerm should have type='text' or type='code'"
                        )
                # Direct text on <role> is NOT valid per MODS schema
                if role_el.text and role_el.text.strip():
                    self.fail(f"role element must not contain direct text: {role_el.text!r}")
        self.assertTrue(found_role_term,
                        "role element must contain roleTerm children")

    def test_mets_header_createdate_is_dynamic(self):
        """metsHdr CREATEDATE must reflect actual export time, not be hardcoded (P2)."""
        ws = Workspace.create("Test")
        df = pd.DataFrame({"record_id": ["rec-001"]})
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        headers = _find_elements(root, "metsHdr", _METS_NS)
        self.assertEqual(len(headers), 1)
        create_date = headers[0].get("CREATEDATE")
        self.assertIsNotNone(create_date)

        # Must NOT be the previously hardcoded value
        self.assertNotEqual(create_date, "2026-05-11T00:00:00Z",
                            "CREATEDATE must be dynamic, not hardcoded")

        # Must match ISO 8601 UTC format YYYY-MM-DDTHH:MM:SSZ
        self.assertRegex(
            create_date,
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            f"CREATEDATE must be ISO 8601 UTC format, got: {create_date}"
        )

        # Should reflect current time (within last minute)
        from datetime import datetime, timezone
        parsed = datetime.strptime(create_date, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta_seconds = abs((now - parsed).total_seconds())
        self.assertLess(delta_seconds, 60,
                        "CREATEDATE should be within 1 minute of export time")

    def test_image_mapped_field_only_for_accepted_review(self):
        """Pending/rejected image analyses must NOT appear in MODS output."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("image.description", "Description", label="Bildbeschreibung"),
        ])
        df = pd.DataFrame({
            "record_id": ["rec-001"],
        })

        # PENDING image analysis (not yet reviewed)
        img = ImageAnalysisResult(
            image_id="img-001",
            filename="test.jpg",
            record_id="rec-001",
            review_status=ImageReviewStatus.PENDING,
            result={"description": "Unreviewed description"},
        )
        ws.image_analyses.append(img)

        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        abstracts = _find_elements(root, "abstract", _MODS_NS)
        abstract_texts = [a.text for a in abstracts]
        self.assertNotIn("Unreviewed description", abstract_texts,
                         "Pending image analyses must not surface in MODS")

    def test_rejected_entities_excluded_from_export(self):
        """Rejected entity reviews must NOT appear in MODS output (P1)."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test"],
        })

        # Add both accepted and rejected entities
        accepted = EntityReview(
            entity_type="PER",
            text="Accepted Person",
            record_id="rec-001",
            status=ReviewStatus.ACCEPTED,
        )
        rejected = EntityReview(
            entity_type="LOC",
            text="Rejected Place",
            record_id="rec-001",
            status=ReviewStatus.REJECTED,
        )
        ws.entity_reviews.append(accepted)
        ws.entity_reviews.append(rejected)

        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        # Accepted person should appear in name elements
        names = _find_elements(root, "name", _MODS_NS)
        name_texts = []
        for name_el in names:
            parts = name_el.findall(f"{{{_MODS_NS}}}namePart")
            name_texts.extend([p.text for p in parts if p.text])
        self.assertIn("Accepted Person", name_texts,
                      "Accepted entities must be in MODS output")

        # Rejected place must NOT appear anywhere
        geos = _find_elements(root, "geographic", _MODS_NS)
        geo_texts = [g.text for g in geos]
        self.assertNotIn("Rejected Place", geo_texts,
                         "Rejected entities must be excluded from MODS output")

    def test_zero_record_limit_respected(self):
        """limit=0 must export 0 records, not full dataset (P2)."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001", "rec-002", "rec-003"],
            "title": ["Title 1", "Title 2", "Title 3"],
        })

        # Export with limit=0
        mets_str = export_mets_mods(df, ws, limit=0)
        root = fromstring(mets_str)

        # Should have 0 dmdSec elements (one per record)
        dmd_secs = _find_elements(root, "dmdSec", _METS_NS)
        self.assertEqual(len(dmd_secs), 0,
                         "limit=0 must result in 0 records exported")

        # Should still have valid METS structure (header, file section, struct map)
        headers = _find_elements(root, "metsHdr", _METS_NS)
        self.assertEqual(len(headers), 1, "METS header must be present even with limit=0")

    def test_nat_datetime_filtered_as_null(self):
        """pd.NaT (datetime null) must be filtered out, not serialized as 'NaT' (P2)."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("date", "DateCreated", label="Datierung"),
        ])
        df = pd.DataFrame({
            "record_id": ["rec-001", "rec-002"],
            "date": [pd.Timestamp("2020-01-01"), pd.NaT],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        # Find all dateIssued elements
        dates = _find_elements(root, "dateIssued", _MODS_NS)
        date_texts = [d.text for d in dates if d.text]

        # Should have the valid date
        self.assertEqual(len(date_texts), 1,
                         "Only 1 valid date should be present (NaT filtered)")
        self.assertIn("2020-01-01", date_texts[0],
                      "Valid date must appear in output")
        # NaT must NOT appear as a literal string
        full_text = " ".join(date_texts)
        self.assertNotIn("NaT", full_text,
                         "NaT placeholders must be filtered, not serialized")

    def test_organization_entities_exported(self):
        """ORG entities must map to MODS names[@type=corporate] (P2)."""
        ws = _ws_basic()
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "title": ["Test"],
        })

        # Add organization entity
        er = EntityReview(
            entity_type="ORG",
            text="Deutsche Nationalbibliothek",
            record_id="rec-001",
            status=ReviewStatus.ACCEPTED,
        )
        ws.entity_reviews.append(er)

        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        # Find corporate names
        names = _find_elements(root, "name", _MODS_NS)
        corp_names = [n for n in names if n.get("type") == "corporate"]
        self.assertGreater(len(corp_names), 0,
                           "ORG entities must create corporate name elements")

        # Verify name part contains the organization
        name_parts = []
        for corp in corp_names:
            parts = corp.findall(f"{{{_MODS_NS}}}namePart")
            name_parts.extend([p.text for p in parts if p.text])
        self.assertIn("Deutsche Nationalbibliothek", name_parts,
                      "Organization name must appear in namePart")

    def test_id_column_fallback_to_first_column(self):
        """When workspace.id_column doesn't exist in data, fallback to first column (P1)."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("identifier", "CatalogIDDigital"),
        ])
        # Set id_column to a name that doesn't exist in the DataFrame
        ws.id_column = "record_id"

        df = pd.DataFrame({
            "identifier": ["obj-001", "obj-002"],
            "data": ["A", "B"],
        })

        # Add entities keyed to the actual first column (identifier)
        er = EntityReview(
            entity_type="PER",
            text="Test Person",
            record_id="obj-001",  # Matches first column, not "record_id"
            status=ReviewStatus.ACCEPTED,
        )
        ws.entity_reviews.append(er)

        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        # Should have 2 dmdSecs (one per row)
        dmd_secs = _find_elements(root, "dmdSec", _METS_NS)
        self.assertEqual(len(dmd_secs), 2,
                         "Should have records despite id_column mismatch")

        # Should have exported the person entity (proves record ID matched correctly)
        names = _find_elements(root, "name", _MODS_NS)
        name_parts = []
        for name in names:
            parts = name.findall(f"{{{_MODS_NS}}}namePart")
            name_parts.extend([p.text for p in parts if p.text])
        self.assertIn("Test Person", name_parts,
                      "Entity lookup must work with correct ID column fallback")

    def test_subject_corporation_mapping(self):
        """SubjectCorporation field maps to MODS subject/name[@type=corporate] (P2)."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("corp_subject", "SubjectCorporation", label="Unternehmensthema"),
        ])
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "corp_subject": ["Deutsche Nationalbibliothek"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        # Find subject elements with nested corporate names
        subjects = _find_elements(root, "subject", _MODS_NS)
        found = False
        for subj in subjects:
            names = subj.findall(f"{{{_MODS_NS}}}name")
            for name in names:
                if name.get("type") == "corporate":
                    parts = name.findall(f"{{{_MODS_NS}}}namePart")
                    for p in parts:
                        if p.text == "Deutsche Nationalbibliothek":
                            found = True
        self.assertTrue(found, "SubjectCorporation must map to subject/name[@type=corporate]")

    def test_repeatable_subjects_split_on_semicolon(self):
        """Repeatable subject fields split on semicolon create separate MODS nodes (P2)."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("subjects", "SubjectTopic", label="Themen", repeatable=True),
        ])
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "subjects": ["Kartographie; Geographie; Linguistik"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        # Find all topic elements
        topics = _find_elements(root, "topic", _MODS_NS)
        topic_texts = [t.text for t in topics]

        # Should have 3 separate topic elements, not one combined
        self.assertEqual(len(topic_texts), 3, "Repeatable subjects must split into separate nodes")
        self.assertIn("Kartographie", topic_texts)
        self.assertIn("Geographie", topic_texts)
        self.assertIn("Linguistik", topic_texts)

    def test_repeatable_creators_split_on_semicolon(self):
        """Repeatable creator fields split on semicolon create separate name nodes (P2)."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("record_id", "CatalogIDDigital"),
            FieldMapping("creators", "Creator", label="Schöpfer", repeatable=True),
        ])
        df = pd.DataFrame({
            "record_id": ["rec-001"],
            "creators": ["Goethe; Schiller; Heine"],
        })
        mets_str = export_mets_mods(df, ws)
        root = fromstring(mets_str)

        # Find all personal name elements with Creator role
        names = _find_elements(root, "name", _MODS_NS)
        creator_parts = []
        for name in names:
            if name.get("type") == "personal":
                roles = name.findall(f"{{{_MODS_NS}}}role")
                # Check if this is a Creator role
                is_creator = any(
                    r.findall(f"{{{_MODS_NS}}}roleTerm")
                    for r in roles
                )
                if is_creator:
                    parts = name.findall(f"{{{_MODS_NS}}}namePart")
                    creator_parts.extend([p.text for p in parts if p.text])

        # Should have 3 separate creator names
        self.assertEqual(len(creator_parts), 3, "Repeatable creators must split into separate nodes")
        self.assertIn("Goethe", creator_parts)
        self.assertIn("Schiller", creator_parts)
        self.assertIn("Heine", creator_parts)


if __name__ == "__main__":
    unittest.main()
