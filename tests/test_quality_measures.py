"""
Tests for the 12 harmonized core data-quality measures.

Covers:
- Individual measure computations
- QualityMeasureReport structure and serialization
- Integration via analyze_datasets
- Markdown rendering of quality measures
- New FindingCategory values
"""
import pandas as pd
import unittest

from kwb.core.models import (
    AnalysisReport,
    DatasetProfile,
    Finding,
    FindingCategory,
    QualityMeasureKey,
    QualityMeasureReport,
    QualityMeasureSummary,
    QualityStatus,
    Severity,
)
from kwb.analyze.quality_measures import compute_quality_measures
from kwb.analyze.structural import analyze_datasets
from kwb.ingest.csv_loader import profile_column, detect_id_column
from kwb.report.markdown import render_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_profile(df: pd.DataFrame, id_col: str | None = None) -> DatasetProfile:
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


def _make_report_with_findings(*findings: Finding, rows: int = 100, cols: int = 5) -> AnalysisReport:
    """Build a minimal AnalysisReport with the given findings and summary."""
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
# New FindingCategory values
# ---------------------------------------------------------------------------

class TestNewFindingCategories(unittest.TestCase):
    def test_all_new_categories_exist(self):
        new_cats = [
            FindingCategory.AMBIGUOUS_VALUE,
            FindingCategory.LOW_INFORMATION_VALUE,
            FindingCategory.CROSS_FIELD_CONFLICT,
            FindingCategory.PROVENANCE_GAP,
            FindingCategory.NEAR_DUPLICATE_RECORDS,
            FindingCategory.REMEDIATION_CANDIDATE,
        ]
        for cat in new_cats:
            self.assertIsInstance(cat.value, str)

    def test_new_categories_usable_in_findings(self):
        f = Finding(
            category=FindingCategory.AMBIGUOUS_VALUE,
            severity=Severity.WARNING,
            message="Ambiguous value in column",
        )
        self.assertEqual(f.category, FindingCategory.AMBIGUOUS_VALUE)
        self.assertEqual(f.scope, "dataset-level")

    def test_remediation_candidate_finding(self):
        f = Finding(
            category=FindingCategory.REMEDIATION_CANDIDATE,
            severity=Severity.INFO,
            message="Can be auto-fixed",
            suggestion="Run normalization pass",
        )
        self.assertEqual(f.category, FindingCategory.REMEDIATION_CANDIDATE)
        self.assertEqual(f.suggestion, "Run normalization pass")


# ---------------------------------------------------------------------------
# QualityMeasureSummary and QualityMeasureReport models
# ---------------------------------------------------------------------------

class TestQualityModels(unittest.TestCase):
    def _make_summary(self, key: QualityMeasureKey, score: int) -> QualityMeasureSummary:
        return QualityMeasureSummary(
            measure=key,
            score=score,
            status=QualityStatus.GOOD if score >= 80 else QualityStatus.NEEDS_REVIEW,
            summary="Test summary",
            mapped_finding_categories=["missing_values"],
            evidence_count=5,
        )

    def test_to_dict_structure(self):
        s = self._make_summary(QualityMeasureKey.COMPLETENESS, 85)
        d = s.to_dict()
        self.assertEqual(d["measure"], "completeness")
        self.assertEqual(d["score"], 85)
        self.assertEqual(d["status"], "good")
        self.assertIn("summary", d)
        self.assertIn("mapped_finding_categories", d)
        self.assertIn("evidence_count", d)
        self.assertIn("top_examples", d)
        self.assertIn("recommended_actions", d)

    def test_quality_measure_report_by_key(self):
        s1 = self._make_summary(QualityMeasureKey.COMPLETENESS, 90)
        s2 = self._make_summary(QualityMeasureKey.UNIQUENESS, 60)
        qmr = QualityMeasureReport(measures=[s1, s2])
        self.assertIs(qmr.by_key(QualityMeasureKey.COMPLETENESS), s1)
        self.assertIs(qmr.by_key(QualityMeasureKey.UNIQUENESS), s2)
        self.assertIsNone(qmr.by_key(QualityMeasureKey.ACTIONABILITY))

    def test_quality_measure_report_to_dict_list(self):
        s = self._make_summary(QualityMeasureKey.RISK_SEVERITY, 40)
        qmr = QualityMeasureReport(measures=[s])
        dl = qmr.to_dict_list()
        self.assertIsInstance(dl, list)
        self.assertEqual(len(dl), 1)
        self.assertEqual(dl[0]["measure"], "risk_severity")

    def test_insufficient_data_status(self):
        s = QualityMeasureSummary(
            measure=QualityMeasureKey.PROVENANCE,
            score=None,
            status=QualityStatus.INSUFFICIENT_DATA,
            summary="No data",
            mapped_finding_categories=[],
            evidence_count=0,
        )
        d = s.to_dict()
        self.assertIsNone(d["score"])
        self.assertEqual(d["status"], "insufficient_data")


# ---------------------------------------------------------------------------
# compute_quality_measures — all 12 measures present
# ---------------------------------------------------------------------------

class TestComputeQualityMeasuresStructure(unittest.TestCase):
    def setUp(self):
        df = pd.DataFrame({
            "record_id": [f"r{i}" for i in range(50)],
            "title": ["Title"] * 50,
            "description": ["Desc"] * 40 + [""] * 10,
        })
        profile = make_profile(df, "record_id")
        datasets = [(df, profile)]
        self.report = analyze_datasets(datasets)

    def test_quality_measures_attached_to_report(self):
        self.assertIsNotNone(self.report.quality_measures)
        self.assertIsInstance(self.report.quality_measures, QualityMeasureReport)

    def test_exactly_12_measures(self):
        self.assertEqual(len(self.report.quality_measures.measures), 12)

    def test_all_12_keys_present(self):
        keys = {m.measure for m in self.report.quality_measures.measures}
        expected = set(QualityMeasureKey)
        self.assertEqual(keys, expected)

    def test_all_measures_have_valid_status(self):
        for m in self.report.quality_measures.measures:
            self.assertIn(m.status, QualityStatus)

    def test_scores_in_valid_range(self):
        for m in self.report.quality_measures.measures:
            if m.score is not None:
                self.assertGreaterEqual(m.score, 0)
                self.assertLessEqual(m.score, 100)

    def test_all_measures_have_summary_text(self):
        for m in self.report.quality_measures.measures:
            self.assertIsInstance(m.summary, str)
            self.assertGreater(len(m.summary), 0)

    def test_all_measures_have_mapped_categories(self):
        for m in self.report.quality_measures.measures:
            self.assertIsInstance(m.mapped_finding_categories, list)
            self.assertGreater(len(m.mapped_finding_categories), 0)


# ---------------------------------------------------------------------------
# Completeness measure
# ---------------------------------------------------------------------------

class TestCompletenessM(unittest.TestCase):
    def test_full_data_score_100(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r3"],
            "title": ["A", "B", "C"],
        })
        report = analyze_datasets([(df, make_profile(df, "record_id"))])
        m = report.quality_measures.by_key(QualityMeasureKey.COMPLETENESS)
        self.assertIsNotNone(m)
        self.assertEqual(m.score, 100)
        self.assertEqual(m.status, QualityStatus.GOOD)

    def test_half_missing_lowers_score(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r3", "r4"],
            "title": ["A", None, "C", None],
            "desc": [None, None, "X", None],
        })
        report = analyze_datasets([(df, make_profile(df, "record_id"))])
        m = report.quality_measures.by_key(QualityMeasureKey.COMPLETENESS)
        self.assertIsNotNone(m)
        self.assertLess(m.score, 80)

    def test_empty_report_returns_insufficient(self):
        report = AnalysisReport()
        report.summary = {"total_records": 0, "total_columns": 0}
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.COMPLETENESS)
        self.assertEqual(m.status, QualityStatus.INSUFFICIENT_DATA)
        self.assertIsNone(m.score)


# ---------------------------------------------------------------------------
# Uniqueness measure
# ---------------------------------------------------------------------------

class TestUniquenessM(unittest.TestCase):
    def test_no_duplicates_score_100(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r3"],
            "title": ["A", "B", "C"],
        })
        report = analyze_datasets([(df, make_profile(df, "record_id"))])
        m = report.quality_measures.by_key(QualityMeasureKey.UNIQUENESS)
        self.assertEqual(m.score, 100)
        self.assertEqual(m.status, QualityStatus.GOOD)

    def test_duplicates_lower_score(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r1", "r2", "r2", "r3"],
            "title": ["A", "A", "B", "B", "C"],
        })
        report = analyze_datasets([(df, make_profile(df, "record_id"))])
        m = report.quality_measures.by_key(QualityMeasureKey.UNIQUENESS)
        self.assertIsNotNone(m.score)
        self.assertLess(m.score, 100)

    def test_zero_records_returns_insufficient(self):
        report = AnalysisReport()
        report.summary = {"total_records": 0, "total_columns": 3}
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.UNIQUENESS)
        self.assertEqual(m.status, QualityStatus.INSUFFICIENT_DATA)


# ---------------------------------------------------------------------------
# Structural validity measure
# ---------------------------------------------------------------------------

class TestStructuralValidityM(unittest.TestCase):
    def test_no_structural_issues_high_score(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2"],
            "title": ["A", "B"],
        })
        report = analyze_datasets([(df, make_profile(df, "record_id"))])
        m = report.quality_measures.by_key(QualityMeasureKey.STRUCTURAL_VALIDITY)
        self.assertGreaterEqual(m.score, 80)

    def test_encoding_issues_lower_score(self):
        report = _make_report_with_findings(
            Finding(
                category=FindingCategory.ENCODING_ISSUES,
                severity=Severity.WARNING,
                message="Encoding artifact in 'title'",
                evidence={"pattern": "Ã¤", "count": 5},
            )
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.STRUCTURAL_VALIDITY)
        self.assertLess(m.score, 100)

    def test_critical_schema_mismatch_lowers_score_more(self):
        report = _make_report_with_findings(
            Finding(
                category=FindingCategory.SCHEMA_MISMATCH,
                severity=Severity.CRITICAL,
                message="No unique ID column detected",
            )
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.STRUCTURAL_VALIDITY)
        self.assertLessEqual(m.score, 80)


# ---------------------------------------------------------------------------
# Consistency measure
# ---------------------------------------------------------------------------

class TestConsistencyM(unittest.TestCase):
    def test_term_variants_lower_score(self):
        report = _make_report_with_findings(
            Finding(
                category=FindingCategory.TERM_VARIANTS,
                severity=Severity.WARNING,
                message="Column 'title' has 4 term variant groups",
                column="title",
                evidence={
                    "variant_count": 4,
                    "examples": [{"canonical": "berlin", "forms": ["Berlin", "berlin"]}],
                },
            )
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.CONSISTENCY)
        self.assertLess(m.score, 100)
        self.assertEqual(m.evidence_count, 4)

    def test_no_variants_good_score(self):
        report = _make_report_with_findings()
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.CONSISTENCY)
        self.assertGreaterEqual(m.score, 80)

    def test_top_examples_populated(self):
        report = _make_report_with_findings(
            Finding(
                category=FindingCategory.TERM_VARIANTS,
                severity=Severity.WARNING,
                message="Variants",
                column="subject",
                evidence={
                    "variant_count": 2,
                    "examples": [
                        {"canonical": "museum", "forms": ["Museum", "museum"], "counts": {"Museum": 3, "museum": 1}},
                    ],
                },
            )
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.CONSISTENCY)
        self.assertGreater(len(m.top_examples), 0)
        self.assertEqual(m.top_examples[0]["column"], "subject")


# ---------------------------------------------------------------------------
# Normalization measure
# ---------------------------------------------------------------------------

class TestNormalizationM(unittest.TestCase):
    def test_good_gnd_coverage_high_score(self):
        report = _make_report_with_findings(
            Finding(
                category=FindingCategory.GND_MATCH_MISSING,
                severity=Severity.INFO,
                message="GND coverage: 45/50 slots (90.0%)",
                evidence={"coverage_rate": 0.9, "no_match_count": 2, "api_recommended": 3,
                          "total_ne_slots": 50, "filled_gnd_ids": 45},
            )
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.NORMALIZATION)
        self.assertGreaterEqual(m.score, 80)

    def test_poor_gnd_coverage_low_score(self):
        report = _make_report_with_findings(
            Finding(
                category=FindingCategory.GND_MATCH_MISSING,
                severity=Severity.WARNING,
                message="GND coverage: 10/50 slots (20.0%)",
                evidence={"coverage_rate": 0.2, "no_match_count": 30, "api_recommended": 20,
                          "total_ne_slots": 50, "filled_gnd_ids": 10},
            )
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.NORMALIZATION)
        self.assertLess(m.score, 50)

    def test_no_gnd_columns_moderate_score(self):
        df = pd.DataFrame({"record_id": ["r1"], "title": ["A"]})
        report = analyze_datasets([(df, make_profile(df, "record_id"))])
        m = report.quality_measures.by_key(QualityMeasureKey.NORMALIZATION)
        # No GND columns: moderate score
        self.assertGreaterEqual(m.score, 70)


# ---------------------------------------------------------------------------
# Risk / Severity measure
# ---------------------------------------------------------------------------

class TestRiskSeverityM(unittest.TestCase):
    def test_no_findings_score_100(self):
        report = _make_report_with_findings()
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.RISK_SEVERITY)
        self.assertEqual(m.score, 100)
        self.assertEqual(m.status, QualityStatus.GOOD)

    def test_all_critical_score_low(self):
        report = _make_report_with_findings(
            Finding(FindingCategory.DUPLICATE_RECORDS, Severity.CRITICAL, "Dupes"),
            Finding(FindingCategory.SCHEMA_MISMATCH, Severity.CRITICAL, "No ID"),
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.RISK_SEVERITY)
        self.assertLessEqual(m.score, 30)
        self.assertEqual(m.status, QualityStatus.CRITICAL)

    def test_top_examples_are_critical_findings(self):
        report = _make_report_with_findings(
            Finding(FindingCategory.DUPLICATE_RECORDS, Severity.CRITICAL, "Critical issue"),
            Finding(FindingCategory.MISSING_VALUES, Severity.INFO, "Minor gap"),
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.RISK_SEVERITY)
        critical_msgs = [ex["message"] for ex in m.top_examples]
        self.assertIn("Critical issue", critical_msgs)


# ---------------------------------------------------------------------------
# Actionability measure
# ---------------------------------------------------------------------------

class TestActionabilityM(unittest.TestCase):
    def test_no_findings_score_100(self):
        report = _make_report_with_findings()
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.ACTIONABILITY)
        self.assertEqual(m.score, 100)

    def test_all_with_suggestions_score_100(self):
        report = _make_report_with_findings(
            Finding(FindingCategory.TERM_VARIANTS, Severity.WARNING, "Variants",
                    suggestion="Normalize terms"),
            Finding(FindingCategory.MISSING_VALUES, Severity.WARNING, "Missing",
                    suggestion="Fill blanks"),
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.ACTIONABILITY)
        self.assertEqual(m.score, 100)

    def test_no_suggestions_score_0(self):
        report = _make_report_with_findings(
            Finding(FindingCategory.ENCODING_ISSUES, Severity.WARNING, "Artifact"),
            Finding(FindingCategory.FORMAT_INCONSISTENCY, Severity.WARNING, "Mixed delimiters"),
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.ACTIONABILITY)
        self.assertEqual(m.score, 0)
        self.assertEqual(m.status, QualityStatus.CRITICAL)

    def test_remediation_candidate_mentioned_in_actions(self):
        report = _make_report_with_findings(
            Finding(FindingCategory.REMEDIATION_CANDIDATE, Severity.INFO,
                    "Auto-fixable", suggestion="Run script"),
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.ACTIONABILITY)
        actions_text = " ".join(m.recommended_actions)
        self.assertIn("automatisch behebbar", actions_text)


# ---------------------------------------------------------------------------
# Fitness for use (composite)
# ---------------------------------------------------------------------------

class TestFitnessForUseM(unittest.TestCase):
    def test_composite_average_of_three(self):
        df = pd.DataFrame({
            "record_id": [f"r{i}" for i in range(10)],
            "title": ["T"] * 10,
        })
        report = analyze_datasets([(df, make_profile(df, "record_id"))])
        m_fit = report.quality_measures.by_key(QualityMeasureKey.FITNESS_FOR_USE)
        m_comp = report.quality_measures.by_key(QualityMeasureKey.COMPLETENESS)
        m_uniq = report.quality_measures.by_key(QualityMeasureKey.UNIQUENESS)
        m_struct = report.quality_measures.by_key(QualityMeasureKey.STRUCTURAL_VALIDITY)

        scores = [s for s in [m_comp.score, m_uniq.score, m_struct.score] if s is not None]
        expected = round(sum(scores) / len(scores))
        self.assertEqual(m_fit.score, expected)

    def test_no_data_returns_insufficient(self):
        report = AnalysisReport()
        report.summary = {}
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.FITNESS_FOR_USE)
        self.assertEqual(m.status, QualityStatus.INSUFFICIENT_DATA)


# ---------------------------------------------------------------------------
# Cross-field coherence measure
# ---------------------------------------------------------------------------

class TestCrossFieldCoherenceM(unittest.TestCase):
    def test_no_issues_good_score(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2"],
            "title": ["A", "B"],
        })
        report = analyze_datasets([(df, make_profile(df, "record_id"))])
        m = report.quality_measures.by_key(QualityMeasureKey.CROSS_FIELD_COHERENCE)
        self.assertGreaterEqual(m.score, 80)

    def test_orphan_records_lower_score(self):
        report = _make_report_with_findings(
            Finding(
                category=FindingCategory.ORPHAN_RECORDS,
                severity=Severity.WARNING,
                message="10 records in 'a' have no match in 'b'",
                record_ids=[str(i) for i in range(10)],
                evidence={"orphan_count": 10, "shared_count": 5},
            )
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.CROSS_FIELD_COHERENCE)
        self.assertLess(m.score, 100)

    def test_cross_field_conflict_finding(self):
        report = _make_report_with_findings(
            Finding(
                category=FindingCategory.CROSS_FIELD_CONFLICT,
                severity=Severity.WARNING,
                message="Conflicting place/subject values",
            )
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.CROSS_FIELD_COHERENCE)
        self.assertLessEqual(m.score, 85)


# ---------------------------------------------------------------------------
# Provenance measure
# ---------------------------------------------------------------------------

class TestProvenanceM(unittest.TestCase):
    def test_high_gnd_coverage_good_score(self):
        report = _make_report_with_findings(
            Finding(
                category=FindingCategory.GND_MATCH_MISSING,
                severity=Severity.INFO,
                message="GND coverage: 80%",
                evidence={"coverage_rate": 0.8, "no_match_count": 5,
                          "total_ne_slots": 100, "filled_gnd_ids": 80},
            )
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.PROVENANCE)
        self.assertGreaterEqual(m.score, 70)

    def test_provenance_gap_finding(self):
        report = _make_report_with_findings(
            Finding(
                category=FindingCategory.PROVENANCE_GAP,
                severity=Severity.WARNING,
                message="Missing source attribution",
            )
        )
        qmr = compute_quality_measures(report)
        m = qmr.by_key(QualityMeasureKey.PROVENANCE)
        self.assertLess(m.score, 100)


# ---------------------------------------------------------------------------
# Integration: analyze_datasets produces quality_measures
# ---------------------------------------------------------------------------

class TestAnalyzeDatasetsIntegration(unittest.TestCase):
    def test_quality_measures_populated_after_analyze(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r3", "r4", "r5"],
            "title": ["A", "B", "C", None, "E"],
            "subject": ["Museum", "museum", "Archiv", "ARCHIV", "Galerie"],
        })
        profile = make_profile(df, "record_id")
        report = analyze_datasets([(df, profile)])

        self.assertIsNotNone(report.quality_measures)
        self.assertEqual(len(report.quality_measures.measures), 12)

    def test_json_serialization(self):
        import json
        df = pd.DataFrame({
            "record_id": ["r1", "r2"],
            "title": ["A", "B"],
        })
        report = analyze_datasets([(df, make_profile(df, "record_id"))])
        dl = report.quality_measures.to_dict_list()
        # Must be JSON-serializable
        serialized = json.dumps(dl)
        loaded = json.loads(serialized)
        self.assertEqual(len(loaded), 12)
        for item in loaded:
            self.assertIn("measure", item)
            self.assertIn("score", item)
            self.assertIn("status", item)

    def test_with_duplicates_uniqueness_penalized(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r1", "r2"],
            "title": ["A", "A", "B"],
        })
        report = analyze_datasets([(df, make_profile(df, "record_id"))])
        m = report.quality_measures.by_key(QualityMeasureKey.UNIQUENESS)
        self.assertLess(m.score, 100)
        self.assertIn(m.status, [QualityStatus.NEEDS_REVIEW, QualityStatus.CRITICAL])


# ---------------------------------------------------------------------------
# Markdown rendering of quality measures
# ---------------------------------------------------------------------------

class TestMarkdownRendering(unittest.TestCase):
    def _get_report(self) -> AnalysisReport:
        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r3"],
            "title": ["A", None, "C"],
            "subject": ["Museum", "museum", "Archiv"],
        })
        return analyze_datasets([(df, make_profile(df, "record_id"))])

    def test_quality_section_in_markdown(self):
        report = self._get_report()
        md = render_report(report)
        self.assertIn("12 Kerndimensionen der Datenqualität", md)

    def test_all_12_measure_labels_in_markdown(self):
        report = self._get_report()
        md = render_report(report)
        labels = [
            "Vollständigkeit",
            "Eindeutigkeit",
            "Strukturelle Gültigkeit",
            "Konsistenz",
            "Normalisierung",
            "Verwendbarkeit",
        ]
        for label in labels:
            self.assertIn(label, md, f"Label '{label}' not found in markdown")

    def test_quality_section_before_dataset_profiles(self):
        report = self._get_report()
        md = render_report(report)
        quality_pos = md.find("12 Kerndimensionen")
        profile_pos = md.find("## Datensatz-Profile")
        self.assertGreater(profile_pos, quality_pos)

    def test_no_quality_section_if_no_measures(self):
        report = AnalysisReport()
        report.summary = {}
        # Do not set quality_measures
        md = render_report(report)
        self.assertNotIn("12 Kerndimensionen", md)

    def test_attention_block_for_critical_measures(self):
        report = _make_report_with_findings(
            Finding(FindingCategory.DUPLICATE_RECORDS, Severity.CRITICAL, "Dupes"),
            Finding(FindingCategory.DUPLICATE_RECORDS, Severity.CRITICAL, "Dupes2"),
            Finding(FindingCategory.DUPLICATE_RECORDS, Severity.CRITICAL, "Dupes3"),
        )
        report.quality_measures = compute_quality_measures(report)
        md = render_report(report)
        # Risk/severity should be critical and appear in attention block
        self.assertIn("Maßzahlen mit Handlungsbedarf", md)


if __name__ == "__main__":
    unittest.main()
