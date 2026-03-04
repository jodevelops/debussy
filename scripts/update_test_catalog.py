#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SuiteResult:
    name: str
    tests: int
    passed: int
    failed: int
    errors: int
    skipped: int

    @property
    def status(self) -> str:
        return "✅" if (self.failed == 0 and self.errors == 0) else "❌"


def discover_test_files(tests_dir: Path) -> list[Path]:
    return sorted(p for p in tests_dir.glob("test_*.py") if p.is_file())


def run_suite(pytest_cmd: str, test_file: Path, repo_root: Path) -> SuiteResult:
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        xml_path = Path(tmp.name)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    cmd = [pytest_cmd, "-q", str(test_file), f"--junitxml={xml_path}"]
    proc = subprocess.run(cmd, cwd=repo_root, env=env, capture_output=True, text=True)

    if not xml_path.exists():
        raise RuntimeError(f"Kein JUnit-XML erzeugt für {test_file}.\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

    root = ET.parse(xml_path).getroot()
    xml_path.unlink(missing_ok=True)

    suite = root.find("testsuite") if root.tag == "testsuites" else root
    if suite is None:
        raise RuntimeError(f"Ungültiges JUnit-XML für {test_file}")

    tests = int(suite.attrib.get("tests", "0"))
    failures = int(suite.attrib.get("failures", "0"))
    errors = int(suite.attrib.get("errors", "0"))
    skipped = int(suite.attrib.get("skipped", "0"))
    passed = tests - failures - errors - skipped

    return SuiteResult(
        name=test_file.name,
        tests=tests,
        passed=passed,
        failed=failures,
        errors=errors,
        skipped=skipped,
    )


def build_table(results: list[SuiteResult]) -> str:
    lines = [
        "| Test-Suite | Bestanden | Fehlgeschlagen | Übersprungen | Status |",
        "|------------|-----------|----------------|--------------|--------|",
    ]

    for r in results:
        lines.append(
            f"| {r.name} | {r.passed}/{r.tests} | {r.failed + r.errors} | {r.skipped} | {r.status} |"
        )

    total_tests = sum(r.tests for r in results)
    total_passed = sum(r.passed for r in results)
    total_failed = sum(r.failed + r.errors for r in results)
    total_skipped = sum(r.skipped for r in results)
    overall_status = "✅" if total_failed == 0 else "❌"

    lines.append(
        f"| **Gesamt** | **{total_passed}/{total_tests}** | **{total_failed}** | **{total_skipped}** | **{overall_status}** |"
    )
    return "\n".join(lines)


def update_catalog(catalog_path: Path, table: str, results: list[SuiteResult]) -> None:
    text = catalog_path.read_text(encoding="utf-8")

    total_tests = sum(r.tests for r in results)
    total_passed = sum(r.passed for r in results)
    total_failed = sum(r.failed + r.errors for r in results)
    total_skipped = sum(r.skipped for r in results)

    status_line = (
        f"**Gesamtstatus:** {total_passed}/{total_tests} Tests bestanden, "
        f"{total_failed} fehlgeschlagen, {total_skipped} übersprungen"
    )
    text = re.sub(r"\*\*Gesamtstatus:\*\*.*", status_line, text, count=1)

    start_marker = "<!-- AUTO-TESTS-START -->"
    end_marker = "<!-- AUTO-TESTS-END -->"

    if start_marker not in text or end_marker not in text:
        replacement = (
            "### Automatische Tests\n\n"
            f"{start_marker}\n{table}\n{end_marker}\n"
            "\n"
            "_Hinweis: Diese Zahlen werden mit `python scripts/update_test_catalog.py --update-doc` "
            "neu berechnet (z. B. im Release-Prozess oder als CI-Schritt)._"
        )
        text = re.sub(
            r"### Automatische Tests\n(?:.|\n)*$",
            replacement,
            text,
            count=1,
        )
    else:
        text = re.sub(
            rf"{re.escape(start_marker)}(?:.|\n)*?{re.escape(end_marker)}",
            f"{start_marker}\n{table}\n{end_marker}",
            text,
            count=1,
        )

    catalog_path.write_text(text, encoding="utf-8")


def check_catalog(catalog_path: Path, expected_table: str) -> int:
    text = catalog_path.read_text(encoding="utf-8")
    m = re.search(
        r"<!-- AUTO-TESTS-START -->\n(?P<table>(?:.|\n)*?)\n<!-- AUTO-TESTS-END -->",
        text,
    )
    if not m:
        print("Fehlende Marker <!-- AUTO-TESTS-START/END --> in docs/FUNKTIONSKATALOG.md", file=sys.stderr)
        return 2

    current = m.group("table").strip()
    if current != expected_table.strip():
        print("Testkatalog ist nicht aktuell. Bitte ausführen:")
        print("  python scripts/update_test_catalog.py --update-doc")
        return 1

    print("Testkatalog ist aktuell.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregiert pytest-Ergebnisse pro tests/test_*.py und aktualisiert docs/FUNKTIONSKATALOG.md")
    parser.add_argument("--pytest", default="pytest", help="Pfad/Befehl für pytest")
    parser.add_argument("--repo-root", default=".", help="Repository-Wurzel")
    parser.add_argument("--update-doc", action="store_true", help="docs/FUNKTIONSKATALOG.md automatisch aktualisieren")
    parser.add_argument("--check-doc", action="store_true", help="prüft, ob docs/FUNKTIONSKATALOG.md zur aktuellen Testlage passt")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    tests = discover_test_files(repo_root / "tests")
    if not tests:
        print("Keine tests/test_*.py gefunden", file=sys.stderr)
        return 2

    results = [run_suite(args.pytest, t, repo_root) for t in tests]
    table = build_table(results)

    if args.update_doc:
        update_catalog(repo_root / "docs" / "FUNKTIONSKATALOG.md", table, results)

    if args.check_doc:
        return check_catalog(repo_root / "docs" / "FUNKTIONSKATALOG.md", table)

    if not args.update_doc:
        print(table)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
