"""
Tests for report/html.py — Interactive HTML curation report.

Strategy:
- Parse generated HTML and verify structure (tabs, sections, tables)
- Verify embedded CSS and JS are present
- Verify HTML escaping prevents XSS
- Verify content surfaces from workspace (entities, dates, dictionary, images)
- Verify authority links use correct URLs
- Verify empty workspaces produce graceful "no data" sections
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kwb.core.workspace import (
    Workspace, FieldMapping, EntityReview, ReviewStatus, CuratedDate,
    DictionaryEntry, ImageAnalysisResult, ImageReviewStatus,
)
from kwb.report.html import render_html_report, render_html_report_bytes


class TestHtmlStructure(unittest.TestCase):
    """Test basic HTML document structure."""

    def test_doctype_and_lang(self):
        """Report must be a valid HTML5 document."""
        ws = Workspace.create("Test")
        html = render_html_report(ws)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn('<html lang="de">', html)

    def test_has_charset_utf8(self):
        """Charset declaration must be UTF-8 (covers German umlauts)."""
        ws = Workspace.create("Test")
        html = render_html_report(ws)
        self.assertIn('<meta charset="utf-8">', html)

    def test_self_contained_no_external_resources(self):
        """No external CSS or JS — must be self-contained for archiving."""
        ws = Workspace.create("Test")
        html = render_html_report(ws)
        # No external link or script tags
        self.assertNotIn('<link rel="stylesheet"', html)
        self.assertNotRegex(html, r'<script\s+src=')
        # But inline <style> and <script> should be present
        self.assertIn("<style>", html)
        self.assertIn("<script>", html)

    def test_all_tabs_present(self):
        """All six tab buttons and sections must be present."""
        ws = Workspace.create("Test")
        html = render_html_report(ws)
        for tab in ("overview", "entities", "dates", "dictionary", "images", "mappings"):
            self.assertIn(f'data-tab="{tab}"', html)
            self.assertIn(f'id="{tab}"', html)

    def test_custom_title(self):
        """Custom title parameter appears in HTML title and header."""
        ws = Workspace.create("MyProject")
        html = render_html_report(ws, title="Mein Bericht")
        self.assertIn("<title>Mein Bericht</title>", html)
        self.assertIn("Mein Bericht</h1>", html)


class TestHtmlEscaping(unittest.TestCase):
    """Test XSS prevention via HTML escaping."""

    def test_workspace_name_is_escaped(self):
        """Malicious workspace name must be HTML-escaped, not interpreted."""
        ws = Workspace.create('<script>alert("xss")</script>')
        html = render_html_report(ws)
        # The literal script tag should not appear in output (only escaped)
        self.assertNotIn('<script>alert("xss")</script>', html)
        # Escaped form should appear
        self.assertIn('&lt;script&gt;', html)

    def test_entity_text_is_escaped(self):
        """Entity text fields are escaped."""
        ws = Workspace.create("Test")
        er = EntityReview(
            entity_type="PER",
            text='<img src=x onerror=alert(1)>',
            status=ReviewStatus.ACCEPTED,
        )
        ws.entity_reviews.append(er)
        html = render_html_report(ws)
        self.assertNotIn('<img src=x onerror=alert(1)>', html)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)


class TestOverviewSection(unittest.TestCase):
    """Test overview section with summary statistics."""

    def test_empty_workspace_shows_zero_counts(self):
        """Empty workspace shows 0 for all counts."""
        ws = Workspace.create("Empty")
        html = render_html_report(ws)
        # Should contain stat cards with 0 values
        self.assertIn("stat-value", html)
        self.assertIn("Wörterbuch-Einträge", html)
        self.assertIn("NER-Entitäten", html)

    def test_counts_reflect_workspace_content(self):
        """Stat counts reflect actual workspace content."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping("col1", "TitleDocMain"),
            FieldMapping("col2", "Creator"),
        ])
        for i in range(3):
            ws.entity_reviews.append(
                EntityReview(entity_type="PER", text=f"Person {i}",
                             status=ReviewStatus.ACCEPTED)
            )
        ws.dates.append(CuratedDate(original="1920", edtf="1920"))

        html = render_html_report(ws)
        # Tab labels should reflect counts
        self.assertIn("NER (3)", html)
        self.assertIn("Mappings (2)", html)
        self.assertIn("Daten (1)", html)


class TestEntitiesSection(unittest.TestCase):
    """Test NER entities section."""

    def test_empty_entities_shows_message(self):
        """No entities shows empty message."""
        ws = Workspace.create("Test")
        html = render_html_report(ws)
        # Section exists but with empty message
        self.assertIn('id="entities"', html)

    def test_entity_appears_in_table(self):
        """Entity data surfaces in the table."""
        ws = Workspace.create("Test")
        er = EntityReview(
            entity_type="PER",
            text="Johann Goethe",
            gnd_id="118540238",
            gnd_preferred="Goethe, Johann Wolfgang von",
            status=ReviewStatus.ACCEPTED,
            confidence=0.95,
        )
        ws.entity_reviews.append(er)
        html = render_html_report(ws)
        self.assertIn("Johann Goethe", html)
        self.assertIn("Goethe, Johann Wolfgang von", html)
        self.assertIn("118540238", html)
        self.assertIn("0.95", html)

    def test_gnd_authority_link(self):
        """GND ID becomes a clickable link to d-nb.info."""
        ws = Workspace.create("Test")
        er = EntityReview(
            entity_type="PER", text="Test", gnd_id="118540238",
            status=ReviewStatus.ACCEPTED,
        )
        ws.entity_reviews.append(er)
        html = render_html_report(ws)
        self.assertIn("https://d-nb.info/gnd/118540238", html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener"', html)

    def test_entity_type_breakdown_bars(self):
        """Entity type distribution rendered as bars."""
        ws = Workspace.create("Test")
        for t, n in [("PER", 5), ("LOC", 3), ("ORG", 2)]:
            for i in range(n):
                ws.entity_reviews.append(
                    EntityReview(entity_type=t, text=f"{t}-{i}",
                                 status=ReviewStatus.PENDING)
                )
        html = render_html_report(ws)
        self.assertIn("Verteilung nach Typ", html)
        self.assertIn("bar-fill", html)


class TestDatesSection(unittest.TestCase):
    """Test EDTF dates section."""

    def test_date_appears_in_table(self):
        """CuratedDate data surfaces in dates table."""
        ws = Workspace.create("Test")
        cd = CuratedDate(
            original="ca. 1920", edtf="1920~",
            confidence=0.9, method="rule",
            record_id="rec-001", column="date_col",
        )
        ws.dates.append(cd)
        html = render_html_report(ws)
        self.assertIn("ca. 1920", html)
        self.assertIn("1920~", html)
        self.assertIn("rec-001", html)
        self.assertIn("date_col", html)


class TestDictionarySection(unittest.TestCase):
    """Test dictionary section with authority links."""

    def test_dictionary_entry_with_gnd(self):
        """Dictionary entry with GND ID renders authority link."""
        ws = Workspace.create("Test")
        entry = DictionaryEntry(
            term="Berlin",
            entity_type="place",
            gnd_id="4005728-7",
            gnd_preferred="Berlin",
        )
        ws.dictionary.append(entry)
        html = render_html_report(ws)
        self.assertIn("Berlin", html)
        self.assertIn("https://d-nb.info/gnd/4005728-7", html)

    def test_dictionary_entry_with_wikidata(self):
        """Dictionary entry with Wikidata ID renders Wikidata link."""
        ws = Workspace.create("Test")
        entry = DictionaryEntry(
            term="Goethe",
            entity_type="person",
            wikidata_id="Q5879",
        )
        ws.dictionary.append(entry)
        html = render_html_report(ws)
        self.assertIn("https://www.wikidata.org/wiki/Q5879", html)

    def test_dictionary_entry_with_geonames(self):
        """Dictionary entry with GeoNames ID renders GeoNames link."""
        ws = Workspace.create("Test")
        entry = DictionaryEntry(
            term="Berlin",
            entity_type="place",
            geonames_id="2950159",
        )
        ws.dictionary.append(entry)
        html = render_html_report(ws)
        self.assertIn("https://www.geonames.org/2950159", html)


class TestImagesSection(unittest.TestCase):
    """Test image analyses section."""

    def test_image_analysis_appears(self):
        """ImageAnalysisResult surfaces in images table."""
        ws = Workspace.create("Test")
        img = ImageAnalysisResult(
            image_id="img-abc-123",
            filename="map.jpg",
            record_id="rec-001",
            review_status=ImageReviewStatus.ACCEPTED,
            result={"description": "A historical map"},
        )
        ws.image_analyses.append(img)
        html = render_html_report(ws)
        self.assertIn("map.jpg", html)
        self.assertIn("A historical map", html)
        self.assertIn("accepted", html)

    def test_long_description_truncated(self):
        """Very long descriptions are truncated for table display."""
        ws = Workspace.create("Test")
        long_desc = "A" * 500
        img = ImageAnalysisResult(
            image_id="img-001",
            filename="test.jpg",
            review_status=ImageReviewStatus.ACCEPTED,
            result={"description": long_desc},
        )
        ws.image_analyses.append(img)
        html = render_html_report(ws)
        # Should not contain the full 500-char string
        self.assertNotIn("A" * 250, html)
        # Should contain truncation indicator
        self.assertIn("…", html)


class TestMappingsSection(unittest.TestCase):
    """Test field mappings section."""

    def test_field_mapping_appears(self):
        """Field mapping data surfaces in mappings table."""
        ws = Workspace.create("Test")
        ws.set_field_mapping([
            FieldMapping(
                csv_column="title",
                goobi_type="TitleDocMain",
                label="Titel",
                repeatable=False,
            ),
        ])
        html = render_html_report(ws)
        self.assertIn("title", html)
        self.assertIn("TitleDocMain", html)
        self.assertIn("Titel", html)


class TestRenderBytes(unittest.TestCase):
    """Test bytes wrapper."""

    def test_returns_utf8_bytes(self):
        """render_html_report_bytes returns UTF-8 encoded bytes."""
        ws = Workspace.create("Tëst")  # umlauts
        result = render_html_report_bytes(ws)
        self.assertIsInstance(result, bytes)
        # Decoding should preserve umlauts
        decoded = result.decode("utf-8")
        self.assertIn("Tëst", decoded)


if __name__ == "__main__":
    unittest.main()
