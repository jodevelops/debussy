"""
Tests for the structured QualityAnalysisReport (Phase 1).

Covers:
- New model classes and their to_dict() serialization
- build_quality_analysis_report() transformation from AnalysisReport
- render_quality_analysis_report() Markdown rendering
- Backwards compatibility: existing render_report() still works
"""

from __future__ import annotations

import unittest

from kwb.core.models import (
    AnalysisReport,
    AnalysisProvenance,
    CellFinding,
    ColumnQualityReport,
    DatasetProfile,
    Finding,
    FindingCategory,
    IssueCluster,
    MeasureSummaryEntry,
    QualityAnalysisReport,
    RecordQualityReport,
    Severity,
    WorkPackageCandidate,
)
from kwb.analyze.quality_report import build_quality_analysis_report
from kwb.analyze.quality_measures import compute_quality_measures
from kwb.report.markdown import render_quality_analysis_report, render_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(source_name: str = "test.csv", rows: int = 100, cols: int = 5) -> DatasetProfile:
    return DatasetProfile(
        source_path=f"/tmp/{source_name}",
        source_name=source_name,
        row_count=rows,
        column_count=cols,
    )


def _make_report(*findings: Finding, rows: int = 100, cols: int = 5) -> AnalysisReport:
    report = AnalysisReport(findings=list(findings))
    report.summary = {
        "total_findings": len(findings),
        "critical": sum(1 for f in findings if f.severity == Severity.CRITICAL),
        "warnings": sum(1 for f in findings if f.severity == Severity.WARNING),
        "info": sum(1 for f in findings if f.severity == Severity.INFO),
        "total_records": rows,
        "total_columns": cols,
        "datasets_analyzed": 1,
    }
    return report


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestMeasureSummaryEntry(unittest.TestCase):
    def test_to_dict_full(self):
        entry = MeasureSummaryEntry(score=72, confidence=0.9, reasoning="Test")
        d = entry.to_dict()
        self.assertEqual(d["score"], 72)
        self.assertEqual(d["confidence"], 0.9)
        self.assertEqual(d["reasoning"], "Test")

    def test_to_dict_none_values(self):
        entry = MeasureSummaryEntry(score=None, confidence=None, reasoning="")
        d = entry.to_dict()
        self.assertIsNone(d["score"])
        self.assertIsNone(d["confidence"])


class TestColumnQualityReport(unittest.TestCase):
    def test_to_dict_structure(self):
        cr = ColumnQualityReport(
            column="title",
            source="ds1.csv",
            measure_summary={
                "completeness": MeasureSummaryEntry(score=80, confidence=None, reasoning="")
            },
            evidence={"fill_rate": 0.8, "unique_count": 100},
            suggested_action="Fill missing titles",
            review_required=True,
        )
        d = cr.to_dict()
        self.assertEqual(d["column"], "title")
        self.assertEqual(d["source"], "ds1.csv")
        self.assertIn("completeness", d["measure_summary"])
        self.assertEqual(d["measure_summary"]["completeness"]["score"], 80)
        self.assertEqual(d["evidence"]["fill_rate"], 0.8)
        self.assertTrue(d["review_required"])

    def test_source_defaults_to_empty_string(self):
        cr = ColumnQualityReport(column="title")
        self.assertEqual(cr.source, "")
        self.assertEqual(cr.to_dict()["source"], "")


class TestRecordQualityReport(unittest.TestCase):
    def test_to_dict_with_severity(self):
        rr = RecordQualityReport(
            record_id="rec_001",
            source="ds1.csv",
            severity=Severity.WARNING,
            issues=["Missing title"],
            confidence=0.85,
            reasoning="Field empty",
            review_required=True,
        )
        d = rr.to_dict()
        self.assertEqual(d["record_id"], "rec_001")
        self.assertEqual(d["source"], "ds1.csv")
        self.assertEqual(d["severity"], "warning")
        self.assertEqual(d["issues"], ["Missing title"])
        self.assertTrue(d["review_required"])

    def test_to_dict_no_severity(self):
        rr = RecordQualityReport(record_id="rec_002")
        d = rr.to_dict()
        self.assertIsNone(d["severity"])

    def test_source_defaults_to_empty_string(self):
        rr = RecordQualityReport(record_id="rec_003")
        self.assertEqual(rr.source, "")
        self.assertEqual(rr.to_dict()["source"], "")


class TestCellFinding(unittest.TestCase):
    def test_to_dict_complete(self):
        cf = CellFinding(
            record_id="rec_001",
            column="date_iso",
            value="31.13.2020",
            severity=Severity.CRITICAL,
            category=FindingCategory.FORMAT_INCONSISTENCY,
            message="Ungültiges Datum",
            confidence=0.95,
            reasoning="Monatswert > 12",
            evidence={"raw_value": "31.13.2020"},
            suggested_action="Datum korrigieren",
            review_required=True,
        )
        d = cf.to_dict()
        self.assertEqual(d["record_id"], "rec_001")
        self.assertEqual(d["column"], "date_iso")
        self.assertEqual(d["severity"], "critical")
        self.assertEqual(d["category"], "format_inconsistency")
        self.assertTrue(d["review_required"])
        self.assertEqual(d["evidence"]["raw_value"], "31.13.2020")


class TestIssueCluster(unittest.TestCase):
    def test_to_dict(self):
        cl = IssueCluster(
            cluster_id="cluster_000_missing_values",
            label="Missing Values",
            category=FindingCategory.MISSING_VALUES,
            affected_columns=["title", "date"],
            affected_records_count=42,
            severity=Severity.WARNING,
            suggested_action="Fehlende Werte ergänzen",
        )
        d = cl.to_dict()
        self.assertEqual(d["cluster_id"], "cluster_000_missing_values")
        self.assertEqual(d["category"], "missing_values")
        self.assertEqual(d["affected_columns"], ["title", "date"])
        self.assertEqual(d["affected_records_count"], 42)


class TestWorkPackageCandidate(unittest.TestCase):
    def test_to_dict(self):
        wp = WorkPackageCandidate(
            title="Duplikate bereinigen",
            description="42 doppelte Records gefunden",
            priority=Severity.CRITICAL,
            affected_columns=["id"],
            estimated_records=42,
            action_type="duplicate_records",
        )
        d = wp.to_dict()
        self.assertEqual(d["title"], "Duplikate bereinigen")
        self.assertEqual(d["priority"], "critical")
        self.assertEqual(d["estimated_records"], 42)


class TestAnalysisProvenance(unittest.TestCase):
    def test_to_dict(self):
        p = AnalysisProvenance(
            analyzed_at="2026-03-24T10:00:00+00:00",
            analyzer_version="0.5.2",
            analysis_mode="rule_based",
            source_name="test.csv",
        )
        d = p.to_dict()
        self.assertEqual(d["analysis_mode"], "rule_based")
        self.assertEqual(d["source_name"], "test.csv")


class TestQualityAnalysisReport(unittest.TestCase):
    def test_to_dict_empty(self):
        qar = QualityAnalysisReport()
        d = qar.to_dict()
        self.assertEqual(d["dataset_profiles"], [])
        self.assertEqual(d["quality_measures"], [])
        self.assertEqual(d["column_reports"], [])
        self.assertEqual(d["record_reports"], [])
        self.assertEqual(d["cell_findings"], [])
        self.assertEqual(d["issue_clusters"], [])
        self.assertEqual(d["work_package_candidates"], [])
        self.assertIsNone(d["analysis_provenance"])

    def test_to_dict_with_single_profile(self):
        ds = _make_profile("demo.csv", rows=500, cols=10)
        qar = QualityAnalysisReport(dataset_profiles=[ds])
        d = qar.to_dict()
        self.assertEqual(len(d["dataset_profiles"]), 1)
        self.assertEqual(d["dataset_profiles"][0]["source_name"], "demo.csv")
        self.assertEqual(d["dataset_profiles"][0]["row_count"], 500)

    def test_to_dict_with_multiple_profiles(self):
        ds1 = _make_profile("a.csv", rows=100, cols=3)
        ds2 = _make_profile("b.csv", rows=200, cols=5)
        qar = QualityAnalysisReport(dataset_profiles=[ds1, ds2])
        d = qar.to_dict()
        self.assertEqual(len(d["dataset_profiles"]), 2)
        names = [p["source_name"] for p in d["dataset_profiles"]]
        self.assertIn("a.csv", names)
        self.assertIn("b.csv", names)

    def test_all_levels_present_in_schema(self):
        """The schema must have all required top-level keys."""
        qar = QualityAnalysisReport()
        d = qar.to_dict()
        required_keys = [
            "dataset_profiles",
            "quality_measures",
            "column_reports",
            "record_reports",
            "cell_findings",
            "issue_clusters",
            "work_package_candidates",
            "analysis_provenance",
        ]
        for key in required_keys:
            self.assertIn(key, d, f"Missing top-level key: {key}")


# ---------------------------------------------------------------------------
# build_quality_analysis_report tests
# ---------------------------------------------------------------------------

class TestBuildQualityAnalysisReport(unittest.TestCase):
    def _make_full_report(self) -> AnalysisReport:
        findings = [
            Finding(
                category=FindingCategory.MISSING_VALUES,
                severity=Severity.WARNING,
                message="Spalte 'title' hat 20% fehlende Werte",
                column="title",
                evidence={"fill_rate": 0.8, "missing_count": 20},
                suggestion="Fehlende Titel ergänzen",
            ),
            Finding(
                category=FindingCategory.DUPLICATE_RECORDS,
                severity=Severity.CRITICAL,
                message="3 doppelte IDs gefunden",
                column="id",
                record_ids=["r001", "r002", "r003"],
                evidence={"duplicate_row_count": 3},
            ),
            Finding(
                category=FindingCategory.FORMAT_INCONSISTENCY,
                severity=Severity.WARNING,
                message="Ungültiges Datumsformat",
                column="date",
                record_ids=["r010"],
                evidence={"raw_value": "31.13.2020"},
            ),
            Finding(
                category=FindingCategory.ENCODING_ISSUES,
                severity=Severity.INFO,
                message="BOM-Zeichen gefunden",
            ),
        ]
        report = _make_report(*findings, rows=200, cols=8)
        profile = _make_profile("sample.csv", rows=200, cols=8)
        report.datasets = [profile]
        report.quality_measures = compute_quality_measures(report)
        return report

    def test_returns_quality_analysis_report_instance(self):
        report = _make_report()
        qar = build_quality_analysis_report(report)
        self.assertIsInstance(qar, QualityAnalysisReport)

    def test_all_dataset_profiles_preserved(self):
        """All datasets must be retained — not just the first one."""
        report = _make_report()
        report.datasets = [
            _make_profile("a.csv", rows=100),
            _make_profile("b.csv", rows=200),
        ]
        qar = build_quality_analysis_report(report)
        self.assertEqual(len(qar.dataset_profiles), 2)
        names = {ds.source_name for ds in qar.dataset_profiles}
        self.assertIn("a.csv", names)
        self.assertIn("b.csv", names)

    def test_single_dataset_profile_mapped(self):
        report = _make_report()
        profile = _make_profile("mydata.csv", rows=300)
        report.datasets = [profile]
        qar = build_quality_analysis_report(report)
        self.assertEqual(len(qar.dataset_profiles), 1)
        self.assertEqual(qar.dataset_profiles[0].source_name, "mydata.csv")

    def test_no_datasets_profiles_empty(self):
        report = _make_report()
        qar = build_quality_analysis_report(report)
        self.assertEqual(qar.dataset_profiles, [])

    def test_quality_measures_populated_from_report(self):
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        self.assertEqual(len(qar.quality_measures), 12)
        keys = {m["measure"] for m in qar.quality_measures}
        self.assertIn("completeness", keys)
        self.assertIn("uniqueness", keys)
        self.assertIn("risk_severity", keys)

    def test_quality_measures_have_required_fields(self):
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        for m in qar.quality_measures:
            self.assertIn("measure", m)
            self.assertIn("score", m)
            self.assertIn("status", m)
            self.assertIn("confidence", m)
            self.assertIn("reasoning", m)
            self.assertIn("evidence", m)

    def test_quality_measures_empty_when_no_qm_report(self):
        report = _make_report()
        # No quality_measures set
        qar = build_quality_analysis_report(report)
        self.assertEqual(qar.quality_measures, [])

    def test_column_reports_built_from_findings(self):
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        col_names = {cr.column for cr in qar.column_reports}
        self.assertIn("title", col_names)
        self.assertIn("id", col_names)

    def test_column_reports_have_measure_summary(self):
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        for cr in qar.column_reports:
            self.assertIn("completeness", cr.measure_summary)
            self.assertIn("semantic_correctness", cr.measure_summary)

    def test_column_review_required_for_warning_columns(self):
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        title_report = next(cr for cr in qar.column_reports if cr.column == "title")
        self.assertTrue(title_report.review_required)

    def test_record_reports_derived_from_findings_with_record_ids(self):
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        record_ids = {rr.record_id for rr in qar.record_reports}
        self.assertIn("r001", record_ids)
        self.assertIn("r002", record_ids)
        self.assertIn("r010", record_ids)

    def test_record_reports_severity(self):
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        r001 = next(rr for rr in qar.record_reports if rr.record_id == "r001")
        self.assertEqual(r001.severity, Severity.CRITICAL)

    def test_cell_findings_for_single_record_findings(self):
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        # r010 / date has exactly 1 record_id -> becomes a cell finding
        cell_cols = {cf.column for cf in qar.cell_findings}
        self.assertIn("date", cell_cols)

    def test_cell_findings_multi_record_not_expanded(self):
        """Findings with multiple record_ids should NOT produce cell findings."""
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        # r001/r002/r003 from DUPLICATE_RECORDS (3 records) -> not cell findings
        dup_cells = [
            cf for cf in qar.cell_findings
            if cf.category == FindingCategory.DUPLICATE_RECORDS
        ]
        self.assertEqual(len(dup_cells), 0)

    def test_issue_clusters_created(self):
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        self.assertGreater(len(qar.issue_clusters), 0)
        cats = {cl.category for cl in qar.issue_clusters}
        self.assertIn(FindingCategory.MISSING_VALUES, cats)
        self.assertIn(FindingCategory.DUPLICATE_RECORDS, cats)

    def test_work_packages_for_warning_critical_only(self):
        """INFO-only clusters must not produce work packages."""
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        for wp in qar.work_package_candidates:
            self.assertIn(wp.priority, (Severity.CRITICAL, Severity.WARNING))

    def test_work_packages_sorted_critical_first(self):
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        priorities = [wp.priority for wp in qar.work_package_candidates]
        sorted_priorities = sorted(priorities, key=lambda s: {Severity.CRITICAL: 0, Severity.WARNING: 1}[s])
        self.assertEqual(priorities, sorted_priorities)

    def test_provenance_set(self):
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        self.assertIsNotNone(qar.analysis_provenance)
        self.assertEqual(qar.analysis_provenance.analysis_mode, "rule_based")
        self.assertIn("sample.csv", qar.analysis_provenance.source_name)

    def test_provenance_source_name_includes_all_datasets(self):
        report = _make_report()
        report.datasets = [_make_profile("a.csv"), _make_profile("b.csv")]
        qar = build_quality_analysis_report(report)
        self.assertIn("a.csv", qar.analysis_provenance.source_name)
        self.assertIn("b.csv", qar.analysis_provenance.source_name)

    def test_to_dict_is_json_compatible(self):
        import json
        report = self._make_full_report()
        qar = build_quality_analysis_report(report)
        d = qar.to_dict()
        # Should not raise
        serialized = json.dumps(d)
        self.assertIsInstance(serialized, str)

    def test_column_reports_distinct_per_dataset_for_same_column_name(self):
        """Same-named columns from different datasets must produce separate reports."""
        from kwb.ingest.csv_loader import profile_column
        import pandas as pd

        def make_ds_with_col(source_name, col_name, values):
            s = pd.Series(values, name=col_name)
            col = profile_column(s)
            ds = _make_profile(source_name)
            ds.columns = [col]
            return ds

        report = _make_report()
        report.datasets = [
            make_ds_with_col("ds1.csv", "title", ["A", "B", "C"]),
            make_ds_with_col("ds2.csv", "title", ["X", None, "Z"]),
        ]
        qar = build_quality_analysis_report(report)
        title_reports = [cr for cr in qar.column_reports if cr.column == "title"]
        # There must be one report per dataset, not one merged entry
        self.assertEqual(len(title_reports), 2)
        sources = {cr.source for cr in title_reports}
        self.assertIn("ds1.csv", sources)
        self.assertIn("ds2.csv", sources)

    def test_issue_cluster_uses_evidence_count_over_record_ids(self):
        """affected_records_count must use evidence fields, not capped record_ids."""
        # Finding has only 2 record_ids in the sample but evidence says 500
        finding = Finding(
            category=FindingCategory.MISSING_VALUES,
            severity=Severity.WARNING,
            message="Viele fehlende Werte",
            column="description",
            record_ids=["r001", "r002"],  # capped sample
            evidence={"missing_count": 500},  # true count
        )
        report = _make_report(finding, rows=1000)
        qar = build_quality_analysis_report(report)
        cluster = next(cl for cl in qar.issue_clusters if cl.category == FindingCategory.MISSING_VALUES)
        self.assertEqual(cluster.affected_records_count, 500)

    def test_issue_cluster_falls_back_to_record_ids_when_no_evidence_count(self):
        finding = Finding(
            category=FindingCategory.TERM_VARIANTS,
            severity=Severity.INFO,
            message="Term-Varianten",
            record_ids=["r001", "r002", "r003"],
            evidence={},  # no count fields
        )
        report = _make_report(finding)
        qar = build_quality_analysis_report(report)
        cluster = next(cl for cl in qar.issue_clusters if cl.category == FindingCategory.TERM_VARIANTS)
        self.assertEqual(cluster.affected_records_count, 3)

    def test_empty_report_does_not_crash(self):
        report = AnalysisReport()
        report.summary = {
            "total_findings": 0,
            "critical": 0,
            "warnings": 0,
            "info": 0,
            "total_records": 0,
            "total_columns": 0,
            "datasets_analyzed": 0,
        }
        qar = build_quality_analysis_report(report)
        self.assertIsInstance(qar, QualityAnalysisReport)
        self.assertEqual(qar.column_reports, [])
        self.assertEqual(qar.record_reports, [])
        self.assertEqual(qar.cell_findings, [])
        self.assertEqual(qar.issue_clusters, [])
        self.assertEqual(qar.work_package_candidates, [])


# ---------------------------------------------------------------------------
# Markdown rendering tests
# ---------------------------------------------------------------------------

class TestRenderQualityAnalysisReport(unittest.TestCase):
    def _build_qar(self) -> QualityAnalysisReport:
        findings = [
            Finding(
                category=FindingCategory.MISSING_VALUES,
                severity=Severity.WARNING,
                message="Spalte 'title' unvollständig",
                column="title",
                evidence={"fill_rate": 0.7, "missing_count": 30},
                suggestion="Titel ergänzen",
            ),
            Finding(
                category=FindingCategory.DUPLICATE_RECORDS,
                severity=Severity.CRITICAL,
                message="Duplikate in ID-Spalte",
                column="id",
                record_ids=["r001", "r002"],
                evidence={"duplicate_row_count": 2},
            ),
        ]
        report = _make_report(*findings, rows=100, cols=5)
        profile = _make_profile("demo.csv", rows=100, cols=5)
        report.datasets = [profile]
        report.quality_measures = compute_quality_measures(report)
        return build_quality_analysis_report(report)

    def test_returns_string(self):
        qar = self._build_qar()
        md = render_quality_analysis_report(qar)
        self.assertIsInstance(md, str)
        self.assertGreater(len(md), 100)

    def test_contains_header(self):
        qar = self._build_qar()
        md = render_quality_analysis_report(qar)
        self.assertIn("# Datenqualitätsbericht", md)

    def test_contains_dataset_summary(self):
        qar = self._build_qar()
        md = render_quality_analysis_report(qar)
        self.assertIn("demo.csv", md)
        self.assertIn("100", md)

    def test_contains_quality_measures_section(self):
        qar = self._build_qar()
        md = render_quality_analysis_report(qar)
        self.assertIn("Kerndimensionen", md)
        self.assertIn("Vollständigkeit", md)

    def test_contains_issue_clusters_section(self):
        qar = self._build_qar()
        md = render_quality_analysis_report(qar)
        self.assertIn("Issue-Cluster", md)

    def test_contains_work_packages_section(self):
        qar = self._build_qar()
        md = render_quality_analysis_report(qar)
        self.assertIn("Arbeitspakete", md)

    def test_contains_provenance(self):
        qar = self._build_qar()
        md = render_quality_analysis_report(qar)
        self.assertIn("rule_based", md)

    def test_dataset_summary_shows_all_datasets(self):
        ds1 = _make_profile("file1.csv", rows=100)
        ds2 = _make_profile("file2.csv", rows=200)
        qar = QualityAnalysisReport(dataset_profiles=[ds1, ds2])
        md = render_quality_analysis_report(qar)
        self.assertIn("file1.csv", md)
        self.assertIn("file2.csv", md)

    def test_no_cell_findings_section_when_empty(self):
        qar = QualityAnalysisReport()
        md = render_quality_analysis_report(qar)
        self.assertNotIn("Zellbefunde", md)

    def test_cell_findings_section_shown_when_present(self):
        qar = QualityAnalysisReport(
            cell_findings=[
                CellFinding(
                    record_id="r001",
                    column="date",
                    severity=Severity.WARNING,
                    category=FindingCategory.FORMAT_INCONSISTENCY,
                    message="Ungültiges Datum",
                )
            ]
        )
        md = render_quality_analysis_report(qar)
        self.assertIn("Zellbefunde", md)
        self.assertIn("r001", md)

    def test_attention_block_for_critical_measures(self):
        qar = self._build_qar()
        md = render_quality_analysis_report(qar)
        self.assertIn("Handlungsbedarf", md)


# ---------------------------------------------------------------------------
# Backwards compatibility: render_report still works
# ---------------------------------------------------------------------------

class TestBackwardsCompatibility(unittest.TestCase):
    def test_render_report_still_works(self):
        findings = [
            Finding(
                category=FindingCategory.MISSING_VALUES,
                severity=Severity.WARNING,
                message="Fehlende Werte",
                column="title",
            )
        ]
        report = _make_report(*findings)
        profile = _make_profile()
        report.datasets = [profile]
        report.quality_measures = compute_quality_measures(report)
        md = render_report(report)
        self.assertIsInstance(md, str)
        self.assertIn("# Datenqualitätsbericht", md)

    def test_existing_analysis_report_unmodified(self):
        """AnalysisReport must retain all its existing fields and methods."""
        report = _make_report(
            Finding(
                category=FindingCategory.DUPLICATE_RECORDS,
                severity=Severity.CRITICAL,
                message="Duplizierte IDs",
            )
        )
        self.assertIsNotNone(report.findings_by_severity)
        self.assertIsNotNone(report.findings_by_category)
        self.assertIn(Severity.CRITICAL, report.findings_by_severity)


if __name__ == "__main__":
    unittest.main()
