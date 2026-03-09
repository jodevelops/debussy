"""
Tests for the Kuratierwerkbank core modules.

Each test function is self-contained with synthetic data,
so tests can run without access to real GIUB data.
"""

import pandas as pd

from kwb.core.models import (
    AnalysisReport,
    DatasetProfile,
    Finding,
    FindingCategory,
    Severity,
)
from kwb.ingest.csv_loader import profile_column, detect_id_column
from kwb.analyze.structural import (
    check_missing_values,
    check_duplicate_records,
    check_encoding_issues,
    check_format_inconsistency,
    check_term_variants,
    check_cross_file_linkage,
    check_gnd_coverage,
    analyze_datasets,
)
from kwb.report.markdown import render_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_profile(df: pd.DataFrame, id_col: str | None = None) -> DatasetProfile:
    """Quick helper to build a DatasetProfile for testing."""
    df_analysis = df.replace("", pd.NA)
    columns = [profile_column(df_analysis[c]) for c in df.columns]
    return DatasetProfile(
        source_path="test.csv",
        source_name="test",
        row_count=len(df),
        column_count=len(df.columns),
        columns=columns,
        id_column=id_col or detect_id_column(df),
    )


# ---------------------------------------------------------------------------
# Core model tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_finding_scope_empty(self):
        f = Finding(
            category=FindingCategory.MISSING_VALUES,
            severity=Severity.WARNING,
            message="test",
        )
        assert f.scope == "dataset-level"

    def test_finding_scope_single(self):
        f = Finding(
            category=FindingCategory.MISSING_VALUES,
            severity=Severity.WARNING,
            message="test",
            record_ids=["rec-001"],
        )
        assert f.scope == "single-record"

    def test_finding_scope_multiple(self):
        f = Finding(
            category=FindingCategory.MISSING_VALUES,
            severity=Severity.WARNING,
            message="test",
            record_ids=["rec-001", "rec-002", "rec-003"],
        )
        assert f.scope == "3 records"

    def test_report_grouping(self):
        report = AnalysisReport(findings=[
            Finding(category=FindingCategory.MISSING_VALUES, severity=Severity.CRITICAL, message="a"),
            Finding(category=FindingCategory.MISSING_VALUES, severity=Severity.WARNING, message="b"),
            Finding(category=FindingCategory.ENCODING_ISSUES, severity=Severity.WARNING, message="c"),
        ])
        assert len(report.findings_by_severity[Severity.CRITICAL]) == 1
        assert len(report.findings_by_severity[Severity.WARNING]) == 2
        assert len(report.findings_by_category[FindingCategory.MISSING_VALUES]) == 2


# ---------------------------------------------------------------------------
# Ingest tests
# ---------------------------------------------------------------------------

class TestIngest:
    def test_detect_id_column(self):
        df = pd.DataFrame({"record_id": ["a", "b", "c"], "value": [1, 2, 3]})
        assert detect_id_column(df) == "record_id"

    def test_detect_id_column_fallback(self):
        df = pd.DataFrame({"code": ["a", "b", "c"], "value": [1, 2, 3]})
        assert detect_id_column(df) == "code"

    def test_detect_no_unique_column(self):
        df = pd.DataFrame({"code": ["a", "a", "c"], "value": ["x", "x", "z"]})
        assert detect_id_column(df) is None

    def test_profile_column_basics(self):
        s = pd.Series(["alpha", "beta", None, "gamma"], name="test")
        p = profile_column(s)
        assert p.name == "test"
        assert p.total_count == 4
        assert p.non_null_count == 3
        assert p.fill_rate == 0.75


# ---------------------------------------------------------------------------
# Analysis tests
# ---------------------------------------------------------------------------

class TestAnalysis:
    def test_missing_values(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r3", "r4"],
            "title": ["A", "", "C", ""],
            "full": ["x", "y", "z", "w"],
        })
        profile = make_profile(df)
        findings = check_missing_values(df, profile)
        title_findings = [f for f in findings if f.column == "title"]
        assert len(title_findings) == 1
        assert title_findings[0].severity == Severity.WARNING

    def test_duplicate_records(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r2", "r3"],
            "value": ["a", "b", "c", "d"],
        })
        profile = make_profile(df, id_col="record_id")
        findings = check_duplicate_records(df, profile)
        assert len(findings) == 1
        assert findings[0].severity == Severity.CRITICAL

    def test_no_duplicates(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r3"],
            "value": ["a", "b", "c"],
        })
        profile = make_profile(df)
        findings = check_duplicate_records(df, profile)
        assert len(findings) == 0

    def test_encoding_artifacts(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2"],
            "title": ["\u00c3\u00a4pfel", "normal"],
        })
        profile = make_profile(df)
        findings = check_encoding_issues(df, profile)
        encoding_finds = [f for f in findings if f.category == FindingCategory.ENCODING_ISSUES
                         and "Encoding artifact" in f.message]
        assert len(encoding_finds) >= 1

    def test_mixed_delimiters(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r3"],
            "tags": ["Berge; Tal", "Fluss, See", "Wald; Wiese, Bach"],
        })
        profile = make_profile(df)
        findings = check_format_inconsistency(df, profile)
        delim_finds = [f for f in findings if "mixed delimiters" in f.message.lower()]
        assert len(delim_finds) >= 1

    def test_term_variants(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r3", "r4"],
            "subject": ["Kirche", "kirche", "KIRCHE", "Moschee"],
        })
        profile = make_profile(df)
        findings = check_term_variants(df, profile)
        assert len(findings) >= 1
        assert findings[0].evidence["variant_count"] >= 1

    def test_cross_file_linkage(self):
        df_a = pd.DataFrame({"record_id": ["r1", "r2", "r3"]})
        df_b = pd.DataFrame({"record_id": ["r2", "r3", "r4"]})
        p_a = make_profile(df_a)
        p_b = make_profile(df_b)
        p_a.source_name = "subjects"
        p_b.source_name = "locations"
        findings = check_cross_file_linkage([(df_a, p_a), (df_b, p_b)])
        orphan_finds = [f for f in findings if f.category == FindingCategory.ORPHAN_RECORDS]
        assert len(orphan_finds) == 2  # orphans in both directions

    def test_gnd_coverage(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r3"],
            "named_entity_1_gnd_id": ["gnd:123", "", ""],
            "named_entity_1_gnd_begruendung": [
                "Match gefunden",
                "Kein GND-Match im Wörterbuch; API-Abfrage empfohlen",
                "Kein GND-Match im Wörterbuch; API-Abfrage empfohlen",
            ],
            "named_entity_1_gnd_konfidenz": ["90%", "", ""],
        })
        profile = make_profile(df)
        findings = check_gnd_coverage(df, profile)
        gnd_finds = [f for f in findings if f.category == FindingCategory.GND_MATCH_MISSING]
        assert len(gnd_finds) >= 1
        assert gnd_finds[0].evidence["api_recommended"] == 2


# ---------------------------------------------------------------------------
# Report tests
# ---------------------------------------------------------------------------

class TestReport:
    def test_render_produces_markdown(self):
        report = AnalysisReport(
            summary={"total_findings": 1, "critical": 0, "warnings": 1,
                     "info": 0, "datasets_analyzed": 1, "total_records": 10,
                     "total_columns": 3},
            findings=[
                Finding(
                    category=FindingCategory.MISSING_VALUES,
                    severity=Severity.WARNING,
                    message="Test finding",
                    column="title",
                ),
            ],
        )
        md = render_report(report)
        assert "# Datenqualitätsbericht" in md
        assert "Test finding" in md
        assert "🟡" in md


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_pipeline(self):
        """Run the entire pipeline on synthetic data."""
        df = pd.DataFrame({
            "record_id": [f"rec-{i:04d}" for i in range(20)],
            "title": ["Berglandschaft"] * 10 + [""] * 10,
            "place": ["Bern; Zürich"] * 5 + ["Basel, Genf"] * 5 + [""] * 10,
        })
        profile = make_profile(df)
        datasets = [(df, profile)]
        report = analyze_datasets(datasets)
        md = render_report(report)

        assert report.summary["total_findings"] > 0
        assert "# Datenqualitätsbericht" in md
        assert len(md) > 100
