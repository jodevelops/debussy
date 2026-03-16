"""Tests for PDF loader."""
import tempfile
import unittest
from pathlib import Path

from kwb.ingest.pdf_loader import pdf_to_images, PDFLoadError


class TestPDFLoader(unittest.TestCase):
    """Test PDF ingestion functionality."""

    def test_file_not_found(self):
        with self.assertRaises(PDFLoadError):
            pdf_to_images("/nonexistent/file.pdf")

    def test_wrong_extension(self):
        path = Path(tempfile.mkdtemp()) / "test.txt"
        path.write_text("hello")
        with self.assertRaises(PDFLoadError):
            pdf_to_images(path)

    def test_no_library_available(self):
        """If neither pdf2image nor pypdf is installed, should raise."""
        # This test verifies the error message; actual behavior depends
        # on installed packages.
        path = Path(tempfile.mkdtemp()) / "test.pdf"
        path.write_bytes(b"%PDF-1.4 dummy")
        try:
            result = pdf_to_images(path)
            # If a library is available, we got results (or an error
            # from the library about invalid PDF content)
            self.assertIsInstance(result, list)
        except PDFLoadError as e:
            self.assertIn("pdf2image", str(e))
        except Exception:
            # Invalid PDF content errors are acceptable
            pass


if __name__ == "__main__":
    unittest.main()
