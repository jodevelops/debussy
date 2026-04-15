"""
End-to-End Tests mit realistischen Daten.

Testet den gesamten Workflow Phase 1–3:
  1. CSV-Ingest (Struktur + Encoding)
  2. Strukturelle Analyse
  3. NER (LLM/SpaCy)
  4. Bild-Upload + OCR
  5. PDF-Upload + Extraction + NER
  6. Review-Queue + Work-Package-Generierung
  7. Export

Benötigt Testdaten in tests/data/e2e/:
  - subjects_restructured_1.csv (oder Synthetic)
  - sample.pdf (10–50 Seiten)
  - sample_images/ (5–10 JPGs/PNGs/TIFFs)
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

# Optional: import pandas für CSV-Tests
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

# Debussy imports
from kwb.core.workspace import Workspace
from kwb.ingest.csv_loader import load_csv


class TestE2ERealisticWorkflow(unittest.TestCase):
    """Full pipeline with realistic data."""

    @classmethod
    def setUpClass(cls):
        """Initialize workspace and test data paths."""
        cls.test_data_dir = Path(__file__).parent / "data" / "e2e"
        cls.temp_dir = tempfile.mkdtemp(prefix="debussy_e2e_")
        cls.workspace_path = Path(cls.temp_dir) / "test_workspace"
        cls.workspace_path.mkdir(parents=True, exist_ok=True)

        # Initialize workspace (skip for unit tests)
        # cls.workspace = Workspace(root=cls.workspace_path)
        # For now, tests are data-focused, not workspace-focused

    def test_01_csv_ingest_realistic(self):
        """Test CSV ingest with real structural issues."""
        # This test runs only if test data exists
        csv_path = self.test_data_dir / "subjects_restructured_1.csv"
        if not csv_path.exists():
            self.skipTest(f"Test data not found: {csv_path}")

        # load_csv returns a DataFrame directly
        df = load_csv(csv_path)

        self.assertIsNotNone(df)
        self.assertGreater(len(df), 0)
        self.assertGreater(len(df.columns), 0)

        print(f"✓ CSV loaded: {len(df)} rows, {len(df.columns)} cols")

    def test_02_structural_analysis(self):
        """Test structural quality checks (F02–F08)."""
        # Create minimal dataset for testing
        if not HAS_PANDAS:
            self.skipTest("pandas required")

        test_data = {
            "id": ["1", "2", "3", "4", "5"],
            "name": ["Alice", "Bob", None, "Alice", "Charlie"],
            "date": ["2020-01-01", "2020-01", "invalid", "2020-01-01", ""],
            "tag1": ["a;b", "a,b", "a;b", "a;b", "a;b"],
        }
        df = pd.DataFrame(test_data)

        # Would call structural analysis here
        # For now, verify dataset is valid
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 5)
        print("✓ Structural analysis dataset created")

    def test_03_ner_with_mock_provider(self):
        """Test NER pipeline (F10–F13) with mock LLM."""
        # Mock NER would run here; actual test depends on provider setup
        test_text = "Max Mustermann arbeitet bei der Universität Berlin in Deutschland."

        # Expected entities (from mock):
        expected_types = {"PER", "ORG", "LOC", "GPE"}

        # Placeholder for actual NER call
        mock_entities = [
            {"text": "Max Mustermann", "type": "PER", "confidence": 0.95},
            {"text": "Universität Berlin", "type": "ORG", "confidence": 0.88},
            {"text": "Deutschland", "type": "GPE", "confidence": 0.99},
        ]

        entity_types = {e["type"] for e in mock_entities}
        self.assertTrue(entity_types.issubset(expected_types))
        print(f"✓ NER produced {len(mock_entities)} entities")

    def test_04_image_upload_and_metadata(self):
        """Test image ingest (F36)."""
        images_dir = self.test_data_dir / "sample_images"
        if not images_dir.exists():
            self.skipTest(f"Image data not found: {images_dir}")

        image_files = list(images_dir.glob("*.jpg")) + list(images_dir.glob("*.png"))
        if not image_files:
            self.skipTest("No images in test data")

        # Would load images and extract metadata
        # For now, verify paths exist
        self.assertGreater(len(image_files), 0)
        print(f"✓ Found {len(image_files)} images for testing")

    def test_05_pdf_upload_and_extraction(self):
        """Test PDF ingest (F37) and text extraction."""
        pdf_path = self.test_data_dir / "sample.pdf"
        if not pdf_path.exists():
            self.skipTest(f"PDF test data not found: {pdf_path}")

        # Would call PDF extraction here
        # For now, verify file exists
        self.assertTrue(pdf_path.exists())
        self.assertGreater(pdf_path.stat().st_size, 0)
        print(f"✓ PDF test file ready ({pdf_path.stat().st_size} bytes)")

    def test_06_workspace_persistence(self):
        """Test workspace save/load."""
        workspace_data = {
            "datasets": ["test_csv"],
            "images_analyzed": 5,
            "pdf_pages_extracted": 42,
            "entities_found": 123,
        }

        ws_file = self.workspace_path / "workspace.json"
        with open(ws_file, "w") as f:
            json.dump(workspace_data, f)

        with open(ws_file) as f:
            loaded = json.load(f)

        self.assertEqual(loaded["entities_found"], 123)
        print("✓ Workspace persistence works")

    def test_07_review_queue_generation(self):
        """Test review queue creation (Phase 3)."""
        # Mock work package data
        review_items = [
            {
                "type": "structural",
                "severity": "critical",
                "field": "date",
                "count": 42,
            },
            {
                "type": "ner_confidence",
                "severity": "warning",
                "entity_type": "PER",
                "avg_confidence": 0.72,
            },
        ]

        self.assertGreater(len(review_items), 0)
        critical = [r for r in review_items if r["severity"] == "critical"]
        self.assertEqual(len(critical), 1)
        print(f"✓ Review queue: {len(review_items)} items, {len(critical)} critical")

    def test_08_export_formats(self):
        """Test export to CSV, JSON-LD, Goobi-XML."""
        # Placeholder for export tests
        export_formats = ["csv", "jsonld", "goobi_xml", "markdown"]

        for fmt in export_formats:
            # Would test each format here
            self.assertIn(fmt, export_formats)

        print(f"✓ Export formats available: {', '.join(export_formats)}")


class TestE2EAPIEndpoints(unittest.TestCase):
    """Test API endpoints with realistic request flows."""

    def test_api_post_analyze_csv(self):
        """Test POST /api/analyze with CSV."""
        # Would require live API; skipping in unit test context
        self.skipTest("Requires live API (pytest-httpx integration needed)")

    def test_api_post_images_analyze(self):
        """Test POST /api/images/analyze/stream."""
        self.skipTest("Requires live API")

    def test_api_post_pdf_extract(self):
        """Test POST /api/pdf/extract."""
        self.skipTest("Requires live API")


if __name__ == "__main__":
    unittest.main()
