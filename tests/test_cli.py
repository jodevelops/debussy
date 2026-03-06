"""Tests für kwb.cli — TEST-08."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path

from kwb.cli import main


# Minimale CSV-Datei, die ingest_csv() klaglos verarbeitet
_MINIMAL_CSV = "id,title,date\n1,Test A,1920\n2,Test B,ca. 1930\n"


class TestCliNoCommand(unittest.TestCase):
    """main() ohne Subkommando gibt Hilfe aus und kehrt mit 0 zurück."""

    def test_no_command_returns_0(self):
        rc = main([])
        self.assertEqual(rc, 0)


class TestCliAnalyze(unittest.TestCase):
    """Tests für das Subkommando 'analyze'."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _csv(self, name: str = "data.csv", content: str = _MINIMAL_CSV) -> str:
        p = Path(self.tmpdir) / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_analyze_missing_file_returns_1(self):
        rc = main(["analyze", "/nonexistent/missing.csv"])
        self.assertEqual(rc, 1)

    def test_analyze_valid_csv_returns_0(self):
        rc = main(["analyze", self._csv()])
        self.assertEqual(rc, 0)

    def test_analyze_output_file_is_written(self):
        out = str(Path(self.tmpdir) / "report.md")
        rc = main(["analyze", self._csv(), "-o", out])
        self.assertEqual(rc, 0)
        self.assertTrue(Path(out).exists(), "Report-Datei wurde nicht erstellt")
        content = Path(out).read_text(encoding="utf-8")
        self.assertGreater(len(content), 0, "Report-Datei ist leer")

    def test_analyze_multiple_files(self):
        a = self._csv("a.csv")
        b = self._csv("b.csv")
        rc = main(["analyze", a, b])
        self.assertEqual(rc, 0)


class TestCliPlan(unittest.TestCase):
    """Tests für das Subkommando 'plan'."""

    _CATALOG = "docs/FUNKTIONSKATALOG.md"

    def test_plan_returns_0(self):
        rc = main(["plan", "--catalog", self._CATALOG, "--top", "3"])
        self.assertEqual(rc, 0)

    def test_plan_output_contains_proposals(self):
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            rc = main(["plan", "--catalog", self._CATALOG, "--top", "2"])
        finally:
            sys.stdout = old_stdout
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Entwicklungsvorschläge", out)

    def test_plan_custom_catalog(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(
                "## 1. Demo\n"
                "| ID | Funktion | Status | Tests | Modul | Hinweis |\n"
                "|----|----------|--------|-------|-------|----------|\n"
                "| F99 | Test-Feature | 🔴 Geplant | 0/0 | `demo.py` | Beispiel |\n"
            )
            catalog_path = f.name
        rc = main(["plan", "--catalog", catalog_path, "--top", "1"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
