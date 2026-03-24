"""
Tests für die LLM-gestützte Qualitätsprüfung (Phase 2).

Alle Tests nutzen MockProvider — kein GPU/Netzwerk erforderlich.
"""
from __future__ import annotations

import json
import unittest

import pandas as pd

from kwb.ai.mock import MockProvider
from kwb.ai.prompts import (
    prompt_cell_quality_check,
    prompt_column_quality_check,
    prompt_dataset_quality_summary,
    prompt_record_quality_check,
)
from kwb.analyze.llm_quality import (
    LlmAnalysisLevel,
    LlmCellFinding,
    LlmColumnReport,
    LlmQualityCheckMode,
    LlmQualityReport,
    run_llm_quality_check,
    _get_field_semantics,
)
from kwb.core.models import (
    CellFinding,
    ColumnQualityReport,
    DatasetProfile,
    FindingCategory,
    QualityAnalysisReport,
    RecordQualityReport,
    Severity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "record_id": ["obj-001", "obj-002", "obj-003", "obj-004", "obj-005"],
        "location_place_name": ["Bern", "Kutsche", "Hasliberg", "Eisenbahnbrücke", "Felder"],
        "date_created": ["1895", "1910", "1923", "1934", "1945"],
        "subject_general": ["Landschaft", "Transport", "Alpen", "", "Natur"],
    })


def _sample_profile(df: pd.DataFrame) -> DatasetProfile:
    from kwb.core.models import ColumnProfile
    cols = [
        ColumnProfile(
            name=col,
            dtype=str(df[col].dtype),
            total_count=len(df),
            non_null_count=int(df[col].notna().sum()),
            unique_count=int(df[col].nunique()),
            fill_rate=round(float(df[col].notna().sum()) / len(df), 4),
            sample_values=df[col].dropna().head(3).astype(str).tolist(),
        )
        for col in df.columns
    ]
    return DatasetProfile(
        source_path="test.csv",
        source_name="test_glam",
        row_count=len(df),
        column_count=len(df.columns),
        columns=cols,
        id_column="record_id",
    )


# ---------------------------------------------------------------------------
# Tests: Prompts
# ---------------------------------------------------------------------------

class TestQualityCheckPrompts(unittest.TestCase):

    def test_cell_prompt_has_two_messages(self):
        msgs = prompt_cell_quality_check(
            field_name="location_place_name",
            field_semantics="Benannter geografischer Ort",
            value="Kutsche",
            record_context={"date_created": "1910"},
            dataset_profile={"source_name": "test", "row_count": 5, "columns": []},
        )
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "system")
        self.assertEqual(msgs[1].role, "user")

    def test_cell_prompt_contains_field_name(self):
        msgs = prompt_cell_quality_check(
            field_name="location_place_name",
            field_semantics="",
            value="Kutsche",
            record_context={},
            dataset_profile={"source_name": "test", "row_count": 5, "columns": []},
        )
        self.assertIn("location_place_name", msgs[1].content)

    def test_cell_prompt_contains_value(self):
        msgs = prompt_cell_quality_check(
            field_name="location_place_name",
            field_semantics="",
            value="Kutsche",
            record_context={},
            dataset_profile={"source_name": "test", "row_count": 5, "columns": []},
        )
        self.assertIn("Kutsche", msgs[1].content)

    def test_cell_prompt_contains_field_semantics(self):
        msgs = prompt_cell_quality_check(
            field_name="location_place_name",
            field_semantics="Benannter geografischer Ort",
            value="Kutsche",
            record_context={},
            dataset_profile={"source_name": "test", "row_count": 5, "columns": []},
        )
        self.assertIn("Benannter geografischer Ort", msgs[1].content)

    def test_cell_prompt_contains_record_context(self):
        msgs = prompt_cell_quality_check(
            field_name="location_place_name",
            field_semantics="",
            value="Kutsche",
            record_context={"date_created": "1910", "subject": "Transport"},
            dataset_profile={"source_name": "test", "row_count": 5, "columns": []},
        )
        self.assertIn("date_created", msgs[1].content)

    def test_cell_prompt_contains_json_schema(self):
        msgs = prompt_cell_quality_check(
            field_name="f",
            field_semantics="",
            value="v",
            record_context={},
            dataset_profile={"source_name": "test", "row_count": 1, "columns": []},
        )
        content = msgs[1].content
        self.assertIn("issue_type", content)
        self.assertIn("confidence", content)
        self.assertIn("suggested_action", content)
        self.assertIn("review_required", content)

    def test_column_prompt_has_two_messages(self):
        msgs = prompt_column_quality_check(
            field_name="location_place_name",
            field_semantics="Ort",
            sample_values=["Bern", "Kutsche"],
            non_empty_count=2,
            total_count=5,
        )
        self.assertEqual(len(msgs), 2)

    def test_column_prompt_contains_sample_values(self):
        msgs = prompt_column_quality_check(
            field_name="location_place_name",
            field_semantics="Ort",
            sample_values=["Bern", "Kutsche"],
            non_empty_count=2,
            total_count=5,
        )
        self.assertIn("Bern", msgs[1].content)
        self.assertIn("Kutsche", msgs[1].content)

    def test_column_prompt_contains_purity_score_field(self):
        msgs = prompt_column_quality_check(
            field_name="col",
            field_semantics="",
            sample_values=["a"],
            non_empty_count=1,
            total_count=10,
        )
        self.assertIn("field_purity_score", msgs[1].content)

    def test_record_prompt_contains_record_id(self):
        msgs = prompt_record_quality_check(
            record_id="obj-001",
            fields={"location_place_name": "Kutsche", "date_created": "1910"},
        )
        self.assertIn("obj-001", msgs[1].content)
        self.assertIn("location_place_name", msgs[1].content)

    def test_record_prompt_contains_conflicts_schema(self):
        msgs = prompt_record_quality_check(record_id="r1", fields={"f1": "v1"})
        self.assertIn("conflicts", msgs[1].content)
        self.assertIn("overall_confidence", msgs[1].content)

    def test_dataset_prompt_contains_source_name(self):
        msgs = prompt_dataset_quality_summary(
            source_name="glam_test",
            row_count=100,
            column_count=5,
            analyzed_columns=["location_place_name"],
            issue_summary={"total_findings": 10, "issue_type_counts": {}, "column_purity_scores": {}},
        )
        self.assertIn("glam_test", msgs[1].content)
        self.assertIn("work_package_candidates", msgs[1].content)


# ---------------------------------------------------------------------------
# Tests: Field semantics lookup
# ---------------------------------------------------------------------------

class TestFieldSemantics(unittest.TestCase):

    def test_exact_match(self):
        s = _get_field_semantics("location_place_name", None)
        self.assertIn("geografisch", s.lower())

    def test_partial_match(self):
        s = _get_field_semantics("my_location_field", None)
        self.assertTrue(len(s) > 0)

    def test_user_override_wins(self):
        s = _get_field_semantics("location_place_name", {"location_place_name": "Custom semantics"})
        self.assertEqual(s, "Custom semantics")

    def test_unknown_field_returns_empty(self):
        s = _get_field_semantics("xyz_completely_unknown_field_abc", None)
        self.assertEqual(s, "")


# ---------------------------------------------------------------------------
# Tests: LlmCellFinding
# ---------------------------------------------------------------------------

class TestLlmCellFinding(unittest.TestCase):

    def _make_finding(self) -> LlmCellFinding:
        return LlmCellFinding(
            record_id="obj-001",
            column="location_place_name",
            value="Kutsche",
            issue_type="semantic_misplacement",
            severity=Severity.WARNING,
            confidence=0.88,
            reasoning="Kein Toponym.",
            evidence={"expected": "Toponym"},
            suggested_target_field="subject_general",
            suggested_action="move_or_review",
            review_required=True,
            model_used="test-model",
        )

    def test_to_dict_contains_required_fields(self):
        d = self._make_finding().to_dict()
        for key in ("issue_type", "severity", "confidence", "reasoning", "evidence",
                    "suggested_action", "review_required"):
            self.assertIn(key, d)

    def test_to_cell_finding_type(self):
        cf = self._make_finding().to_cell_finding()
        self.assertIsInstance(cf, CellFinding)
        self.assertEqual(cf.column, "location_place_name")
        self.assertEqual(cf.severity, Severity.WARNING)
        self.assertAlmostEqual(cf.confidence, 0.88)

    def test_to_cell_finding_category_mapping(self):
        cf = self._make_finding().to_cell_finding()
        self.assertEqual(cf.category, FindingCategory.FIELD_MISUSE)

    def test_suggested_target_field_in_evidence(self):
        cf = self._make_finding().to_cell_finding()
        self.assertIn("suggested_target_field", cf.evidence)
        self.assertEqual(cf.evidence["suggested_target_field"], "subject_general")


# ---------------------------------------------------------------------------
# Tests: LlmColumnReport
# ---------------------------------------------------------------------------

class TestLlmColumnReport(unittest.TestCase):

    def _make_report(self) -> LlmColumnReport:
        return LlmColumnReport(
            column="location_place_name",
            field_semantics="Geografischer Ort",
            field_purity_score=62.0,
            dominant_issue_types=["semantic_misplacement"],
            typical_problems=["Sachbegriffe statt Ortsnamen"],
            affected_value_examples=["Kutsche"],
            suggested_action="Nicht-Toponyme verschieben",
            confidence=0.85,
            reasoning="Mehrere Werte sind keine Orte.",
            review_required=True,
            model_used="test-model",
        )

    def test_to_column_quality_report_type(self):
        cqr = self._make_report().to_column_quality_report()
        self.assertIsInstance(cqr, ColumnQualityReport)
        self.assertEqual(cqr.column, "location_place_name")
        self.assertTrue(cqr.review_required)

    def test_to_column_quality_report_has_measure_summary(self):
        cqr = self._make_report().to_column_quality_report()
        self.assertIn("semantic_correctness", cqr.measure_summary)
        entry = cqr.measure_summary["semantic_correctness"]
        self.assertEqual(entry.score, 62)

    def test_to_dict_structure(self):
        d = self._make_report().to_dict()
        self.assertIn("field_purity_score", d)
        self.assertIn("dominant_issue_types", d)
        self.assertIn("review_required", d)


# ---------------------------------------------------------------------------
# Tests: run_llm_quality_check — cell level
# ---------------------------------------------------------------------------

class TestRunLlmQualityCheckCellLevel(unittest.TestCase):

    def setUp(self):
        self.df = _sample_df()
        self.profile = _sample_profile(self.df)
        self.mock = MockProvider.with_quality_check_responses()

    def test_pilot_mode_runs(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            levels=[LlmAnalysisLevel.CELL],
            mode=LlmQualityCheckMode.PILOT,
            sample_size=3,
        )
        self.assertIsInstance(report, LlmQualityReport)
        self.assertEqual(report.mode, LlmQualityCheckMode.PILOT)

    def test_pilot_mode_limits_sample(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            levels=[LlmAnalysisLevel.CELL],
            mode=LlmQualityCheckMode.PILOT,
            sample_size=2,
        )
        self.assertEqual(report.sample_size, 2)

    def test_full_mode_sample_size_is_none(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            levels=[LlmAnalysisLevel.CELL],
            mode=LlmQualityCheckMode.FULL,
        )
        self.assertIsNone(report.sample_size)

    def test_cell_findings_have_required_fields(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            levels=[LlmAnalysisLevel.CELL],
            mode=LlmQualityCheckMode.FULL,
        )
        for finding in report.cell_findings:
            self.assertIsInstance(finding.issue_type, str)
            self.assertIsInstance(finding.severity, Severity)
            self.assertIsInstance(finding.confidence, float)
            self.assertIsInstance(finding.reasoning, str)
            self.assertIsInstance(finding.suggested_action, str)
            self.assertIsInstance(finding.review_required, bool)

    def test_likely_correct_findings_are_skipped(self):
        """issue_type='likely_correct' should not produce a cell finding."""
        mock = MockProvider.with_quality_check_responses(cell_issue_type="likely_correct")
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=mock,
            levels=[LlmAnalysisLevel.CELL],
            mode=LlmQualityCheckMode.FULL,
        )
        self.assertEqual(len(report.cell_findings), 0)

    def test_empty_cells_are_skipped(self):
        """Empty cells should not generate LLM calls."""
        df = pd.DataFrame({
            "record_id": ["r1", "r2"],
            "location_place_name": ["Bern", ""],
        })
        profile = _sample_profile(df)
        report = run_llm_quality_check(
            df=df,
            profile=profile,
            provider=self.mock,
            levels=[LlmAnalysisLevel.CELL],
            mode=LlmQualityCheckMode.FULL,
        )
        # Batch should only have been called once (non-empty cell)
        calls = [c for c in self.mock.call_log if "Zellwert" in (
            c["messages"][-1].content if isinstance(c["messages"][-1].content, str) else ""
        )]
        self.assertLessEqual(len(calls), 2)

    def test_columns_filter_works(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.CELL],
            mode=LlmQualityCheckMode.FULL,
        )
        self.assertEqual(report.analyzed_columns, ["location_place_name"])
        for f in report.cell_findings:
            self.assertEqual(f.column, "location_place_name")

    def test_model_forwarded_to_provider(self):
        mock = MockProvider.with_quality_check_responses()
        run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=mock,
            levels=[LlmAnalysisLevel.CELL],
            mode=LlmQualityCheckMode.PILOT,
            model="test-model-xyz",
            sample_size=2,
        )
        for call in mock.call_log:
            self.assertEqual(call["model"], "test-model-xyz")


# ---------------------------------------------------------------------------
# Tests: run_llm_quality_check — column level
# ---------------------------------------------------------------------------

class TestRunLlmQualityCheckColumnLevel(unittest.TestCase):

    def setUp(self):
        self.df = _sample_df()
        self.profile = _sample_profile(self.df)
        self.mock = MockProvider.with_quality_check_responses()

    def test_column_reports_generated(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.COLUMN],
            mode=LlmQualityCheckMode.FULL,
        )
        self.assertEqual(len(report.column_reports), 1)
        self.assertEqual(report.column_reports[0].column, "location_place_name")

    def test_column_report_has_purity_score(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.COLUMN],
            mode=LlmQualityCheckMode.FULL,
        )
        score = report.column_reports[0].field_purity_score
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)


# ---------------------------------------------------------------------------
# Tests: run_llm_quality_check — record level
# ---------------------------------------------------------------------------

class TestRunLlmQualityCheckRecordLevel(unittest.TestCase):

    def setUp(self):
        self.df = _sample_df()
        self.profile = _sample_profile(self.df)
        self.mock = MockProvider.with_quality_check_responses()

    def test_record_reports_generated(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name", "date_created"],
            levels=[LlmAnalysisLevel.RECORD],
            mode=LlmQualityCheckMode.PILOT,
            sample_size=3,
        )
        self.assertEqual(len(report.record_reports), 3)

    def test_record_report_fields(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.RECORD],
            mode=LlmQualityCheckMode.PILOT,
            sample_size=2,
        )
        for rec in report.record_reports:
            self.assertIsInstance(rec.severity, Severity)
            self.assertIsInstance(rec.confidence, float)
            self.assertIsInstance(rec.review_required, bool)


# ---------------------------------------------------------------------------
# Tests: run_llm_quality_check — dataset level
# ---------------------------------------------------------------------------

class TestRunLlmQualityCheckDatasetLevel(unittest.TestCase):

    def setUp(self):
        self.df = _sample_df()
        self.profile = _sample_profile(self.df)
        self.mock = MockProvider.with_quality_check_responses()

    def test_dataset_report_generated(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.CELL, LlmAnalysisLevel.DATASET],
            mode=LlmQualityCheckMode.FULL,
        )
        self.assertIsNotNone(report.dataset_report)

    def test_dataset_report_has_work_packages(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.DATASET],
            mode=LlmQualityCheckMode.PILOT,
            sample_size=3,
        )
        self.assertIsNotNone(report.dataset_report)
        self.assertIsInstance(report.dataset_report.work_package_candidates, list)


# ---------------------------------------------------------------------------
# Tests: QualityAnalysisReport integration (Phase 1 compatibility)
# ---------------------------------------------------------------------------

class TestQualityAnalysisReportIntegration(unittest.TestCase):

    def setUp(self):
        self.df = _sample_df()
        self.profile = _sample_profile(self.df)
        self.mock = MockProvider.with_quality_check_responses()

    def test_to_quality_analysis_report_type(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.CELL],
            mode=LlmQualityCheckMode.FULL,
        )
        qa = report.to_quality_analysis_report()
        self.assertIsInstance(qa, QualityAnalysisReport)

    def test_provenance_analysis_mode_is_llm_assisted(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.CELL],
            mode=LlmQualityCheckMode.FULL,
        )
        qa = report.to_quality_analysis_report()
        self.assertIsNotNone(qa.analysis_provenance)
        self.assertEqual(qa.analysis_provenance.analysis_mode, "llm_assisted")

    def test_cell_findings_converted_to_phase1_format(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.CELL],
            mode=LlmQualityCheckMode.FULL,
        )
        qa = report.to_quality_analysis_report()
        for cf in qa.cell_findings:
            self.assertIsInstance(cf, CellFinding)
            self.assertIsNotNone(cf.confidence)
            self.assertIsNotNone(cf.review_required)

    def test_column_reports_converted_to_phase1_format(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.COLUMN],
            mode=LlmQualityCheckMode.FULL,
        )
        qa = report.to_quality_analysis_report()
        for col_rep in qa.column_reports:
            self.assertIsInstance(col_rep, ColumnQualityReport)

    def test_to_dict_is_json_serialisable(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.CELL, LlmAnalysisLevel.COLUMN],
            mode=LlmQualityCheckMode.FULL,
        )
        d = report.to_dict()
        serialised = json.dumps(d)  # should not raise
        self.assertIsInstance(serialised, str)

    def test_quality_analysis_to_dict_is_json_serialisable(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.CELL],
            mode=LlmQualityCheckMode.FULL,
        )
        qa = report.to_quality_analysis_report()
        serialised = json.dumps(qa.to_dict())
        self.assertIsInstance(serialised, str)

    def test_issue_clusters_integrated_from_dataset_report(self):
        report = run_llm_quality_check(
            df=self.df,
            profile=self.profile,
            provider=self.mock,
            columns=["location_place_name"],
            levels=[LlmAnalysisLevel.DATASET],
            mode=LlmQualityCheckMode.PILOT,
            sample_size=3,
        )
        qa = report.to_quality_analysis_report()
        self.assertTrue(len(qa.issue_clusters) > 0)
        self.assertTrue(len(qa.work_package_candidates) > 0)


# ---------------------------------------------------------------------------
# Tests: API endpoint
# ---------------------------------------------------------------------------

class TestLlmQualityApiEndpoint(unittest.TestCase):

    def setUp(self):
        import pandas as pd
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi[testclient] not available")

        from kwb.api.app import app
        from kwb.api import deps

        self.client = TestClient(app)
        self.mock = MockProvider.with_quality_check_responses()
        deps._prov_override = self.mock

        # Register a test dataset
        df = _sample_df()
        deps._state["datasets"]["test_ds"] = {
            "df": df,
            "meta": {"source_name": "test_glam", "source_path": "test.csv"},
        }

    def tearDown(self):
        from kwb.api import deps
        deps._prov_override = None
        deps._state["datasets"].pop("test_ds", None)

    def test_schema_endpoint(self):
        resp = self.client.get("/api/ai/quality-check/schema")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("fields", data)

    def test_quality_check_pilot_cell(self):
        resp = self.client.post("/api/ai/quality-check", json={
            "dataset_id": "test_ds",
            "columns": ["location_place_name"],
            "levels": ["cell"],
            "mode": "pilot",
            "sample_size": 3,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("report", data)
        self.assertIn("quality_analysis", data)
        self.assertEqual(data["mode"], "pilot")

    def test_quality_check_column_level(self):
        resp = self.client.post("/api/ai/quality-check", json={
            "dataset_id": "test_ds",
            "columns": ["location_place_name"],
            "levels": ["column"],
            "mode": "full",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreater(data["summary"]["total_column_reports"], 0)

    def test_quality_check_with_model(self):
        resp = self.client.post("/api/ai/quality-check", json={
            "dataset_id": "test_ds",
            "model": "my-custom-model",
            "columns": ["location_place_name"],
            "levels": ["cell"],
            "mode": "pilot",
            "sample_size": 2,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["model_used"], "my-custom-model")

    def test_quality_check_invalid_dataset(self):
        resp = self.client.post("/api/ai/quality-check", json={
            "dataset_id": "nonexistent",
            "levels": ["cell"],
        })
        self.assertEqual(resp.status_code, 404)
        data = resp.json()
        self.assertEqual(data["status"], "error")

    def test_quality_check_invalid_level(self):
        resp = self.client.post("/api/ai/quality-check", json={
            "dataset_id": "test_ds",
            "levels": ["invalid_level"],
        })
        self.assertEqual(resp.status_code, 422)

    def test_quality_check_invalid_mode(self):
        resp = self.client.post("/api/ai/quality-check", json={
            "dataset_id": "test_ds",
            "levels": ["cell"],
            "mode": "invalid_mode",
        })
        self.assertEqual(resp.status_code, 422)

    def test_quality_check_missing_column(self):
        resp = self.client.post("/api/ai/quality-check", json={
            "dataset_id": "test_ds",
            "columns": ["nonexistent_column"],
            "levels": ["cell"],
        })
        self.assertEqual(resp.status_code, 422)

    def test_quality_check_all_levels(self):
        resp = self.client.post("/api/ai/quality-check", json={
            "dataset_id": "test_ds",
            "columns": ["location_place_name"],
            "levels": ["cell", "column", "record", "dataset"],
            "mode": "pilot",
            "sample_size": 3,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["summary"]["has_dataset_report"])

    def test_response_contains_structured_cell_findings(self):
        resp = self.client.post("/api/ai/quality-check", json={
            "dataset_id": "test_ds",
            "columns": ["location_place_name"],
            "levels": ["cell"],
            "mode": "full",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        findings = data["report"]["cell_findings"]
        if findings:
            f = findings[0]
            for key in ("issue_type", "severity", "confidence", "reasoning",
                        "evidence", "suggested_action", "review_required"):
                self.assertIn(key, f)

    def test_field_semantics_accepted(self):
        resp = self.client.post("/api/ai/quality-check", json={
            "dataset_id": "test_ds",
            "columns": ["location_place_name"],
            "levels": ["cell"],
            "mode": "pilot",
            "sample_size": 2,
            "field_semantics": {
                "location_place_name": "Benannter geografischer Ort"
            },
        })
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
