"""Tests for XLSX loader."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from kwb.ingest.xlsx_loader import load_xlsx, ingest_xlsx, XLSXLoadError


class TestXLSXLoader(unittest.TestCase):
    """Test XLSX ingestion functionality."""

    def _make_xlsx(self, data: dict, filename: str = "test.xlsx") -> Path:
        """Create a temporary XLSX file from a dict of columns."""
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("openpyxl not installed")

        df = pd.DataFrame(data)
        path = Path(tempfile.mkdtemp()) / filename
        df.to_excel(str(path), index=False, engine="openpyxl")
        return path

    def test_load_basic(self):
        path = self._make_xlsx({
            "id": ["1", "2", "3"],
            "title": ["Foo", "Bar", "Baz"],
        })
        df = load_xlsx(path)
        self.assertEqual(len(df), 3)
        self.assertEqual(list(df.columns), ["id", "title"])
        # All columns should be string type
        for col in df.columns:
            non_null = df[col].dropna()
            for v in non_null:
                self.assertIsInstance(v, str)

    def test_empty_cells_become_na(self):
        path = self._make_xlsx({
            "id": ["1", "2"],
            "value": ["hello", ""],
        })
        df = load_xlsx(path)
        self.assertTrue(pd.isna(df.loc[1, "value"]))

    def test_max_rows_exceeded(self):
        path = self._make_xlsx({"id": [str(i) for i in range(100)]})
        with self.assertRaises(XLSXLoadError):
            load_xlsx(path, max_rows=10)

    def test_unsupported_extension(self):
        path = Path(tempfile.mkdtemp()) / "test.txt"
        path.write_text("hello")
        with self.assertRaises(XLSXLoadError):
            load_xlsx(path)

    def test_ingest_xlsx_returns_profile(self):
        path = self._make_xlsx({
            "record_id": ["a1", "a2", "a3"],
            "title": ["T1", "T2", "T3"],
        })
        df, profile = ingest_xlsx(path)
        self.assertEqual(profile.row_count, 3)
        self.assertEqual(profile.column_count, 2)
        self.assertEqual(profile.id_column, "record_id")


if __name__ == "__main__":
    unittest.main()
