"""Tests for test image fixtures and image_loader integration."""
import unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "images"


class TestImageFixtures(unittest.TestCase):
    """Verify generated test images are structurally valid."""

    def _files(self, *exts):
        return [p for p in sorted(FIXTURES.iterdir()) if p.suffix.lower() in exts]

    def test_fixture_directory_exists(self):
        self.assertTrue(FIXTURES.is_dir(), "fixtures/images directory missing")

    def test_png_count(self):
        self.assertGreaterEqual(len(self._files(".png")), 3)

    def test_tiff_count(self):
        self.assertGreaterEqual(len(self._files(".tif", ".tiff")), 2)

    def test_jpeg_count(self):
        self.assertGreaterEqual(len(self._files(".jpg", ".jpeg")), 2)

    def test_png_signatures(self):
        for p in self._files(".png"):
            data = p.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", f"{p.name}: bad PNG signature")

    def test_jpeg_markers(self):
        for p in self._files(".jpg", ".jpeg"):
            data = p.read_bytes()
            self.assertEqual(data[:2], b"\xff\xd8", f"{p.name}: bad JPEG SOI")
            self.assertEqual(data[-2:], b"\xff\xd9", f"{p.name}: bad JPEG EOI")

    def test_tiff_byte_order(self):
        for p in self._files(".tif", ".tiff"):
            data = p.read_bytes()
            self.assertIn(data[:2], (b"II", b"MM"), f"{p.name}: bad TIFF byte-order mark")

    def test_image_loader_reads_all(self):
        from kwb.ingest.image_loader import scan_image_directory
        profiles = scan_image_directory(str(FIXTURES), load_base64=False)
        self.assertEqual(len(profiles), 9)
        for p in profiles:
            self.assertEqual(p.errors, [], f"{p.filename}: unexpected errors {p.errors}")

    def test_png_dimensions_parsed(self):
        from kwb.ingest.image_loader import scan_image_directory
        pngs = [
            p for p in scan_image_directory(str(FIXTURES), load_base64=False)
            if p.filename.endswith(".png")
        ]
        for p in pngs:
            self.assertEqual(p.width, 120, f"{p.filename}: unexpected width {p.width}")
            self.assertEqual(p.height, 120, f"{p.filename}: unexpected height {p.height}")

    def test_base64_loading(self):
        from kwb.ingest.image_loader import ingest_image
        sample = next(iter(FIXTURES.glob("*.png")))
        prof = ingest_image(sample, load_base64=True)
        self.assertTrue(len(prof.base64_data) > 0)
        self.assertTrue(prof.hash_sha256 != "")


if __name__ == "__main__":
    unittest.main()
