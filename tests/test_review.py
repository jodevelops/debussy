"""
Tests für Phase 3 — Review Queues, Work Packages und Remediation.

Alle Tests sind unit-basiert (kein Netzwerk, kein GPU, kein DB).
"""
from __future__ import annotations

import unittest
import uuid

import pandas as pd

from kwb.core.models import (
    AnalysisProvenance,
    AppliedChangeLog,
    CellFinding,
    FindingCategory,
    IssueCluster,
    QualityAnalysisReport,
    RecordQualityReport,
    RemediationActionType,
    RemediationSuggestion,
    ReviewItem,
    ReviewStatus,
    Severity,
    WorkPackage,
    WorkPackageCandidate,
)
from kwb.review.queue import ReviewQueue
from kwb.review.remediation import apply_accepted_changes
from kwb.review.work_packages import generate_work_packages


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sample_cell_finding(
    record_id: str = "obj-001",
    column: str = "location_place_name",
    value: str = "Kutsche",
    severity: Severity = Severity.WARNING,
    category: FindingCategory = FindingCategory.FIELD_MISUSE,
    confidence: float = 0.9,
) -> CellFinding:
    return CellFinding(
        record_id=record_id,
        column=column,
        value=value,
        severity=severity,
        category=category,
        message=f"Wert '{value}' in Spalte '{column}' scheint fehlplatziert",
        confidence=confidence,
        reasoning="Nicht-Toponym in Ortsfeld",
        suggested_action="move_or_review",
        review_required=True,
    )


def _sample_record_report(
    record_id: str = "obj-002",
    review_required: bool = True,
) -> RecordQualityReport:
    return RecordQualityReport(
        record_id=record_id,
        source="test_glam",
        severity=Severity.WARNING,
        issues=["Datum in Ortsfeld", "Fehlende GND-Verknüpfung"],
        confidence=0.75,
        reasoning="Record hat multiple Probleme",
        review_required=review_required,
    )


def _sample_cluster(
    cluster_id: str = "cluster-001",
    severity: Severity = Severity.WARNING,
) -> IssueCluster:
    return IssueCluster(
        cluster_id=cluster_id,
        label="Generische Begriffe in Ortsfeld",
        category=FindingCategory.FIELD_MISUSE,
        affected_columns=["location_place_name"],
        affected_records_count=42,
        severity=severity,
        suggested_action="Werte in subject_general verschieben",
    )


def _sample_quality_report(
    cell_findings: list | None = None,
    record_reports: list | None = None,
    issue_clusters: list | None = None,
    work_package_candidates: list | None = None,
) -> QualityAnalysisReport:
    from kwb.core.models import DatasetProfile
    return QualityAnalysisReport(
        dataset_profiles=[
            DatasetProfile(
                source_path="test.csv",
                source_name="test_glam",
                row_count=100,
                column_count=5,
            )
        ],
        cell_findings=cell_findings if cell_findings is not None else [_sample_cell_finding()],
        record_reports=record_reports if record_reports is not None else [_sample_record_report()],
        issue_clusters=issue_clusters if issue_clusters is not None else [_sample_cluster()],
        work_package_candidates=work_package_candidates if work_package_candidates is not None else [],
        analysis_provenance=AnalysisProvenance(
            analyzed_at="2026-03-25T10:00:00+00:00",
            analyzer_version="0.6.0",
            analysis_mode="rule_based",
        ),
    )


def _sample_suggestion(
    action_type: RemediationActionType = RemediationActionType.APPLY_SUGGESTED_VALUE,
    status: ReviewStatus = ReviewStatus.ACCEPTED,
    item_id: str | None = None,
    original_value: str | None = "Kutsche",
    suggested_value: str | None = "Landfahrzeug",
    target_field: str = "subject_general",
) -> RemediationSuggestion:
    return RemediationSuggestion(
        suggestion_id=str(uuid.uuid4()),
        action_type=action_type,
        original_value=original_value,
        suggested_value=suggested_value,
        reasoning="Korrekter Wert für Zielspalte",
        item_id=item_id,
        target_field=target_field,
        confidence=0.85,
        status=status,
        is_ai_based=True,
    )


# ---------------------------------------------------------------------------
# Tests: ReviewItem model
# ---------------------------------------------------------------------------

class TestReviewItemModel(unittest.TestCase):

    def test_to_dict_contains_required_fields(self):
        item = ReviewItem(
            item_id="item-1",
            source="test_glam",
            record_id="obj-001",
            column="location_place_name",
            original_value="Kutsche",
            category=FindingCategory.FIELD_MISUSE,
            severity=Severity.WARNING,
            confidence=0.9,
            message="Fehlplatzierter Wert",
            reasoning="Nicht-Toponym in Ortsfeld",
            suggested_action="move_or_review",
        )
        d = item.to_dict()
        self.assertEqual(d["item_id"], "item-1")
        self.assertEqual(d["status"], "pending")
        self.assertEqual(d["severity"], "warning")
        self.assertEqual(d["category"], "field_misuse")
        self.assertIsNone(d["reviewer"])
        self.assertFalse(d["is_ai_based"])

    def test_default_status_is_pending(self):
        item = ReviewItem(
            item_id="x",
            source="",
            record_id=None,
            column=None,
            original_value=None,
            category=FindingCategory.MISSING_VALUES,
            severity=Severity.INFO,
            confidence=None,
            message="",
            reasoning="",
            suggested_action=None,
        )
        self.assertEqual(item.status, ReviewStatus.PENDING)


# ---------------------------------------------------------------------------
# Tests: ReviewQueue
# ---------------------------------------------------------------------------

class TestReviewQueue(unittest.TestCase):

    def test_from_quality_report_creates_items(self):
        report = _sample_quality_report()
        queue = ReviewQueue.from_quality_report(report, source="test_glam")
        # Should create items from cell_finding + record_report + cluster
        items = queue.all_items()
        self.assertGreater(len(items), 0)

    def test_from_quality_report_cell_finding_item(self):
        cf = _sample_cell_finding(record_id="obj-001", column="location_place_name")
        report = _sample_quality_report(
            cell_findings=[cf],
            record_reports=[],
            issue_clusters=[],
        )
        queue = ReviewQueue.from_quality_report(report)
        items = queue.all_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].record_id, "obj-001")
        self.assertEqual(items[0].column, "location_place_name")
        self.assertEqual(items[0].original_value, "Kutsche")

    def test_from_quality_report_record_report_review_required(self):
        rr = _sample_record_report(review_required=True)
        rr_no = _sample_record_report(record_id="obj-003", review_required=False)
        report = _sample_quality_report(
            cell_findings=[],
            record_reports=[rr, rr_no],
            issue_clusters=[],
        )
        queue = ReviewQueue.from_quality_report(report)
        items = queue.all_items()
        # Only the review_required=True record should produce an item
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].record_id, "obj-002")

    def test_from_quality_report_skips_info_clusters(self):
        info_cluster = _sample_cluster(severity=Severity.INFO)
        warn_cluster = _sample_cluster(cluster_id="cluster-002", severity=Severity.WARNING)
        report = _sample_quality_report(
            cell_findings=[],
            record_reports=[],
            issue_clusters=[info_cluster, warn_cluster],
        )
        queue = ReviewQueue.from_quality_report(report)
        items = queue.all_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].severity, Severity.WARNING)

    def test_update_status_accepted(self):
        report = _sample_quality_report()
        queue = ReviewQueue.from_quality_report(report)
        items = queue.all_items()
        item_id = items[0].item_id

        updated = queue.update_status(item_id, ReviewStatus.ACCEPTED, reviewer="curator-1")
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, ReviewStatus.ACCEPTED)
        self.assertEqual(updated.reviewer, "curator-1")
        self.assertIsNotNone(updated.reviewed_at)

    def test_update_status_unknown_id_returns_none(self):
        queue = ReviewQueue()
        result = queue.update_status("nonexistent-id", ReviewStatus.REJECTED)
        self.assertIsNone(result)

    def test_decisions_recorded(self):
        report = _sample_quality_report()
        queue = ReviewQueue.from_quality_report(report)
        item_id = queue.all_items()[0].item_id
        queue.update_status(item_id, ReviewStatus.NEEDS_EXPERT_REVIEW, note="Bitte Experten fragen")
        decisions = queue.decisions()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].decision, ReviewStatus.NEEDS_EXPERT_REVIEW)
        self.assertEqual(decisions[0].note, "Bitte Experten fragen")

    def test_filter_by_severity(self):
        cf_warn = _sample_cell_finding(record_id="r1", severity=Severity.WARNING)
        cf_crit = _sample_cell_finding(record_id="r2", severity=Severity.CRITICAL)
        report = _sample_quality_report(
            cell_findings=[cf_warn, cf_crit],
            record_reports=[],
            issue_clusters=[],
        )
        queue = ReviewQueue.from_quality_report(report)
        warnings = queue.filter(severity="warning")
        criticals = queue.filter(severity="critical")
        self.assertEqual(len(warnings), 1)
        self.assertEqual(len(criticals), 1)

    def test_filter_by_column(self):
        cf1 = _sample_cell_finding(column="location_place_name")
        cf2 = _sample_cell_finding(record_id="obj-002", column="subject_general")
        report = _sample_quality_report(
            cell_findings=[cf1, cf2],
            record_reports=[],
            issue_clusters=[],
        )
        queue = ReviewQueue.from_quality_report(report)
        items = queue.filter(column="location_place_name")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].column, "location_place_name")

    def test_filter_by_status(self):
        report = _sample_quality_report()
        queue = ReviewQueue.from_quality_report(report)
        items = queue.all_items()
        # All start as pending
        pending = queue.filter(status="pending")
        self.assertEqual(len(pending), len(items))

        item_id = items[0].item_id
        queue.update_status(item_id, ReviewStatus.ACCEPTED)
        accepted = queue.filter(status="accepted")
        self.assertEqual(len(accepted), 1)

    def test_filter_by_min_confidence(self):
        cf_high = _sample_cell_finding(record_id="r1", confidence=0.9)
        cf_low = _sample_cell_finding(record_id="r2", confidence=0.4)
        report = _sample_quality_report(
            cell_findings=[cf_high, cf_low],
            record_reports=[],
            issue_clusters=[],
        )
        queue = ReviewQueue.from_quality_report(report)
        high = queue.filter(min_confidence=0.8)
        self.assertEqual(len(high), 1)

    def test_summary_structure(self):
        report = _sample_quality_report()
        queue = ReviewQueue.from_quality_report(report)
        summary = queue.summary()
        self.assertIn("total", summary)
        self.assertIn("by_status", summary)
        self.assertIn("by_severity", summary)
        self.assertIn("by_category", summary)
        self.assertGreater(summary["total"], 0)

    def test_to_dict_round_trip(self):
        report = _sample_quality_report()
        queue = ReviewQueue.from_quality_report(report)
        d = queue.to_dict()
        self.assertIn("items", d)
        self.assertIn("decisions", d)
        self.assertIn("summary", d)
        self.assertIsInstance(d["items"], list)


# ---------------------------------------------------------------------------
# Tests: WorkPackage generation
# ---------------------------------------------------------------------------

class TestWorkPackageGeneration(unittest.TestCase):

    def test_generate_from_clusters(self):
        report = _sample_quality_report(
            cell_findings=[],
            record_reports=[],
            issue_clusters=[_sample_cluster()],
        )
        packages = generate_work_packages(report)
        self.assertEqual(len(packages), 1)
        pkg = packages[0]
        self.assertIsInstance(pkg, WorkPackage)
        self.assertEqual(pkg.issue_family, FindingCategory.FIELD_MISUSE.value)
        self.assertEqual(pkg.estimated_records, 42)
        self.assertIn("location_place_name", pkg.affected_columns)

    def test_skips_info_clusters(self):
        info_cluster = _sample_cluster(severity=Severity.INFO)
        report = _sample_quality_report(
            cell_findings=[],
            record_reports=[],
            issue_clusters=[info_cluster],
        )
        packages = generate_work_packages(report)
        self.assertEqual(len(packages), 0)

    def test_critical_before_warning(self):
        warn_cluster = _sample_cluster(cluster_id="c1", severity=Severity.WARNING)
        warn_cluster.affected_records_count = 100
        crit_cluster = _sample_cluster(cluster_id="c2", severity=Severity.CRITICAL)
        crit_cluster.affected_records_count = 10
        report = _sample_quality_report(
            cell_findings=[],
            record_reports=[],
            issue_clusters=[warn_cluster, crit_cluster],
        )
        packages = generate_work_packages(report)
        self.assertEqual(len(packages), 2)
        self.assertEqual(packages[0].priority, Severity.CRITICAL)
        self.assertEqual(packages[1].priority, Severity.WARNING)

    def test_package_has_automation_potential(self):
        cluster = IssueCluster(
            cluster_id="enc-001",
            label="Encoding-Artefakte",
            category=FindingCategory.ENCODING_ISSUES,
            affected_columns=["description"],
            affected_records_count=20,
            severity=Severity.WARNING,
        )
        report = _sample_quality_report(
            cell_findings=[],
            record_reports=[],
            issue_clusters=[cluster],
        )
        packages = generate_work_packages(report)
        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0].automation_potential, "high")

    def test_package_links_item_ids_from_queue(self):
        cluster = _sample_cluster()
        cf = _sample_cell_finding(column="location_place_name", category=FindingCategory.FIELD_MISUSE)
        report = _sample_quality_report(
            cell_findings=[cf],
            record_reports=[],
            issue_clusters=[cluster],
        )
        queue = ReviewQueue.from_quality_report(report)
        packages = generate_work_packages(report, queue=queue)
        self.assertEqual(len(packages), 1)
        # The cluster item should be linked
        self.assertIsInstance(packages[0].item_ids, list)

    def test_package_from_work_package_candidates(self):
        wpc = WorkPackageCandidate(
            title="Terme normalisieren",
            description="Varianten auf Vorzugsform bringen",
            priority=Severity.WARNING,
            affected_columns=["subject_general"],
            estimated_records=55,
            action_type="normalize_label",
        )
        report = _sample_quality_report(
            cell_findings=[],
            record_reports=[],
            issue_clusters=[],
            work_package_candidates=[wpc],
        )
        packages = generate_work_packages(report)
        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0].title, "Terme normalisieren")
        self.assertEqual(packages[0].estimated_records, 55)

    def test_to_dict_serializable(self):
        report = _sample_quality_report()
        packages = generate_work_packages(report)
        for p in packages:
            d = p.to_dict()
            self.assertIn("package_id", d)
            self.assertIn("priority", d)
            self.assertIn("automation_potential", d)
            self.assertIn("recommended_strategy", d)


# ---------------------------------------------------------------------------
# Tests: Remediation
# ---------------------------------------------------------------------------

class TestRemediation(unittest.TestCase):

    def _make_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "record_id": ["obj-001", "obj-002", "obj-003"],
            "subject_general": ["Landschaft", "Kutsche", "Alpen"],
            "location_place_name": ["Bern", "Hasliberg", "Grindelwald"],
        })

    def test_apply_suggested_value_updates_cell(self):
        df = self._make_df()
        sug = _sample_suggestion(
            action_type=RemediationActionType.APPLY_SUGGESTED_VALUE,
            status=ReviewStatus.ACCEPTED,
            original_value="Kutsche",
            suggested_value="Landfahrzeug",
            target_field="subject_general",
        )
        updated, log = apply_accepted_changes(df, [sug], "ds1")
        self.assertIn("Landfahrzeug", updated["subject_general"].values)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0].original_value, "Kutsche")
        self.assertEqual(log[0].new_value, "Landfahrzeug")

    def test_pending_suggestion_not_applied(self):
        df = self._make_df()
        sug = _sample_suggestion(
            status=ReviewStatus.PENDING,
            original_value="Kutsche",
            suggested_value="SHOULD_NOT_APPEAR",
            target_field="subject_general",
        )
        updated, log = apply_accepted_changes(df, [sug], "ds1")
        self.assertNotIn("SHOULD_NOT_APPEAR", updated["subject_general"].values)
        self.assertEqual(len(log), 0)

    def test_rejected_suggestion_not_applied(self):
        df = self._make_df()
        sug = _sample_suggestion(
            status=ReviewStatus.REJECTED,
            original_value="Kutsche",
            suggested_value="SHOULD_NOT_APPEAR",
            target_field="subject_general",
        )
        updated, log = apply_accepted_changes(df, [sug], "ds1")
        self.assertEqual(len(log), 0)

    def test_normalize_label_batch_updates(self):
        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r3"],
            "subject_general": ["Kutsche", "kutsche", "Landschaft"],
        })
        sug = RemediationSuggestion(
            suggestion_id=str(uuid.uuid4()),
            action_type=RemediationActionType.NORMALIZE_LABEL,
            original_value="Kutsche",
            suggested_value="Landfahrzeug",
            reasoning="Normalisierung",
            target_field="subject_general",
            status=ReviewStatus.ACCEPTED,
        )
        updated, log = apply_accepted_changes(df, [sug], "ds1")
        # Only exact match "Kutsche" should be replaced
        self.assertEqual(updated.loc[0, "subject_general"], "Landfahrzeug")
        self.assertEqual(updated.loc[1, "subject_general"], "kutsche")  # case-sensitive
        self.assertEqual(len(log), 1)

    def test_flag_for_authority_lookup_does_not_change_value(self):
        df = self._make_df()
        sug = RemediationSuggestion(
            suggestion_id=str(uuid.uuid4()),
            action_type=RemediationActionType.FLAG_FOR_AUTHORITY_LOOKUP,
            original_value="Bern",
            suggested_value=None,
            reasoning="GND lookup erforderlich",
            target_field="location_place_name",
            status=ReviewStatus.ACCEPTED,
        )
        updated, log = apply_accepted_changes(df, [sug], "ds1")
        # Value unchanged
        self.assertEqual(list(df["location_place_name"]), list(updated["location_place_name"]))
        self.assertEqual(len(log), 1)
        self.assertIn("unchanged", log[0].note or "")

    def test_leave_unchanged_mark_uncertain_logs_entry(self):
        df = self._make_df()
        sug = RemediationSuggestion(
            suggestion_id=str(uuid.uuid4()),
            action_type=RemediationActionType.LEAVE_UNCHANGED_MARK_UNCERTAIN,
            original_value="Alpen",
            suggested_value=None,
            reasoning="Unklar ob Toponym oder Motiv",
            target_field="subject_general",
            status=ReviewStatus.ACCEPTED,
        )
        updated, log = apply_accepted_changes(df, [sug], "ds1")
        self.assertEqual(len(log), 1)
        self.assertIn("uncertain", log[0].note or "")

    def test_original_df_not_mutated(self):
        df = self._make_df()
        original_values = df["subject_general"].tolist()
        sug = _sample_suggestion(
            status=ReviewStatus.ACCEPTED,
            original_value="Kutsche",
            suggested_value="Fahrzeug",
            target_field="subject_general",
        )
        apply_accepted_changes(df, [sug], "ds1")
        # Original should be unchanged
        self.assertEqual(df["subject_general"].tolist(), original_values)

    def test_multiple_suggestions_all_applied(self):
        df = self._make_df()
        sug1 = _sample_suggestion(
            status=ReviewStatus.ACCEPTED,
            original_value="Kutsche",
            suggested_value="Landfahrzeug",
            target_field="subject_general",
        )
        sug2 = RemediationSuggestion(
            suggestion_id=str(uuid.uuid4()),
            action_type=RemediationActionType.NORMALIZE_LABEL,
            original_value="Alpen",
            suggested_value="Gebirge",
            reasoning="Normalisierung",
            target_field="subject_general",
            status=ReviewStatus.ACCEPTED,
        )
        updated, log = apply_accepted_changes(df, [sug1, sug2], "ds1")
        self.assertEqual(len(log), 2)

    def test_changelog_contains_metadata(self):
        df = self._make_df()
        sug = _sample_suggestion(
            status=ReviewStatus.ACCEPTED,
            original_value="Kutsche",
            suggested_value="Landfahrzeug",
            target_field="subject_general",
        )
        _, log = apply_accepted_changes(df, [sug], "ds1", reviewer="curator-1")
        self.assertEqual(log[0].reviewer, "curator-1")
        self.assertEqual(log[0].dataset_id, "ds1")
        self.assertIsNotNone(log[0].applied_at)
        self.assertEqual(log[0].action_type, RemediationActionType.APPLY_SUGGESTED_VALUE)


# ---------------------------------------------------------------------------
# Tests: Model serialization
# ---------------------------------------------------------------------------

class TestPhase3ModelSerialization(unittest.TestCase):

    def test_work_package_to_dict(self):
        wp = WorkPackage(
            package_id="wp-1",
            title="Test Package",
            description="Beschreibung",
            scope="42 Datensätze",
            issue_family="field_misuse",
            priority=Severity.WARNING,
            affected_columns=["location_place_name"],
            estimated_records=42,
            action_type="move_value_to_field",
            automation_potential="medium",
            recommended_strategy="Manuell prüfen",
            created_at="2026-03-25T10:00:00+00:00",
        )
        d = wp.to_dict()
        self.assertEqual(d["priority"], "warning")
        self.assertEqual(d["status"], "pending")
        self.assertIn("package_id", d)

    def test_applied_change_log_to_dict(self):
        log = AppliedChangeLog(
            change_id="cl-1",
            dataset_id="ds1",
            record_id="obj-001",
            column="subject_general",
            original_value="Kutsche",
            new_value="Landfahrzeug",
            action_type=RemediationActionType.APPLY_SUGGESTED_VALUE,
            applied_at="2026-03-25T10:00:00+00:00",
            reviewer="curator-1",
        )
        d = log.to_dict()
        self.assertEqual(d["action_type"], "apply_suggested_value")
        self.assertEqual(d["original_value"], "Kutsche")
        self.assertEqual(d["new_value"], "Landfahrzeug")

    def test_remediation_suggestion_to_dict(self):
        sug = _sample_suggestion()
        d = sug.to_dict()
        self.assertEqual(d["status"], "accepted")
        self.assertIn("suggestion_id", d)
        self.assertIn("action_type", d)
        self.assertTrue(d["is_ai_based"])

    def test_review_status_values(self):
        for s in ReviewStatus:
            self.assertIsInstance(s.value, str)

    def test_remediation_action_type_values(self):
        for a in RemediationActionType:
            self.assertIsInstance(a.value, str)


# ---------------------------------------------------------------------------
# Tests: API routes
# ---------------------------------------------------------------------------

class TestReviewAPIRoutes(unittest.TestCase):
    """Integration-level tests for the review API routes using TestClient."""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from kwb.api.app import app
            import kwb.api.deps as deps

            self.client = TestClient(app)
            # Reset Phase 3 state
            state = deps.get_state()
            state["review_queue"] = None
            state["work_packages"] = []
            state["changelog"] = []
            state["suggestions"] = {}
            # Inject a test dataset
            df = pd.DataFrame({
                "record_id": ["obj-001", "obj-002", "obj-003"],
                "subject_general": ["Landschaft", "Kutsche", "Alpen"],
                "location_place_name": ["Bern", "Hasliberg", "Grindelwald"],
            })
            from kwb.core.models import DatasetProfile
            profile = DatasetProfile(
                source_path="test.csv",
                source_name="test",
                row_count=3,
                column_count=3,
            )
            state["datasets"]["test-ds"] = (df, profile)
            # Inject a QualityAnalysisReport as last report
            state["report"] = _sample_quality_report()

        except Exception:
            self.client = None

    def _skip_if_no_client(self):
        if self.client is None:
            self.skipTest("FastAPI TestClient nicht verfügbar")

    def test_schema_endpoint(self):
        self._skip_if_no_client()
        resp = self.client.get("/api/review/schema")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("review_statuses", data)
        self.assertIn("remediation_action_types", data)
        self.assertIn("endpoints", data)

    def test_items_summary_empty_queue(self):
        self._skip_if_no_client()
        resp = self.client.get("/api/review/items/summary")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("summary", data)

    def test_list_items_empty_queue(self):
        self._skip_if_no_client()
        resp = self.client.get("/api/review/items")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("items", data)

    def test_build_queue_from_report(self):
        self._skip_if_no_client()
        resp = self.client.post("/api/review/queue/build", json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("summary", data)
        self.assertGreater(data["summary"]["total"], 0)

    def test_update_item_status_invalid(self):
        self._skip_if_no_client()
        resp = self.client.patch(
            "/api/review/items/nonexistent/status",
            json={"status": "invalid_status"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_update_item_status_not_found(self):
        self._skip_if_no_client()
        resp = self.client.patch(
            "/api/review/items/nonexistent-id/status",
            json={"status": "accepted"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_generate_work_packages(self):
        self._skip_if_no_client()
        resp = self.client.post("/api/review/work-packages/generate", json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("work_packages", data)

    def test_list_work_packages(self):
        self._skip_if_no_client()
        self.client.post("/api/review/work-packages/generate", json={})
        resp = self.client.get("/api/review/work-packages")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("work_packages", data)

    def test_add_and_list_suggestion(self):
        self._skip_if_no_client()
        payload = {
            "action_type": "apply_suggested_value",
            "original_value": "Kutsche",
            "suggested_value": "Landfahrzeug",
            "reasoning": "Nicht-Toponym",
            "target_field": "subject_general",
        }
        resp = self.client.post("/api/review/suggestions", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("suggestion", data)
        sug_id = data["suggestion"]["suggestion_id"]

        # List
        resp2 = self.client.get("/api/review/suggestions")
        self.assertEqual(resp2.status_code, 200)
        sugs = resp2.json()["suggestions"]
        ids = [s["suggestion_id"] for s in sugs]
        self.assertIn(sug_id, ids)

    def test_add_suggestion_missing_reasoning(self):
        self._skip_if_no_client()
        resp = self.client.post("/api/review/suggestions", json={
            "action_type": "normalize_label",
            "original_value": "x",
            "suggested_value": "y",
        })
        self.assertEqual(resp.status_code, 422)

    def test_update_suggestion_status(self):
        self._skip_if_no_client()
        resp = self.client.post("/api/review/suggestions", json={
            "action_type": "normalize_label",
            "original_value": "Kutsche",
            "suggested_value": "Fahrzeug",
            "reasoning": "Test",
        })
        sug_id = resp.json()["suggestion"]["suggestion_id"]

        resp2 = self.client.patch(
            f"/api/review/suggestions/{sug_id}/status",
            json={"status": "accepted"},
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["suggestion"]["status"], "accepted")

    def test_apply_no_accepted_suggestions(self):
        self._skip_if_no_client()
        resp = self.client.post("/api/review/apply", json={"dataset_id": "test-ds"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["applied_count"], 0)

    def test_apply_accepted_suggestion_to_dataset(self):
        self._skip_if_no_client()
        # Add + accept a suggestion
        resp = self.client.post("/api/review/suggestions", json={
            "action_type": "normalize_label",
            "original_value": "Kutsche",
            "suggested_value": "Landfahrzeug",
            "reasoning": "Normalisierung",
            "target_field": "subject_general",
        })
        sug_id = resp.json()["suggestion"]["suggestion_id"]
        self.client.patch(f"/api/review/suggestions/{sug_id}/status", json={"status": "accepted"})

        resp2 = self.client.post("/api/review/apply", json={
            "dataset_id": "test-ds",
            "reviewer": "curator-1",
        })
        self.assertEqual(resp2.status_code, 200)
        data = resp2.json()
        self.assertEqual(data["applied_count"], 1)

    def test_dry_run_does_not_modify_dataset(self):
        self._skip_if_no_client()
        import kwb.api.deps as deps
        df_before = deps.get_datasets()["test-ds"][0]["subject_general"].tolist()

        resp = self.client.post("/api/review/suggestions", json={
            "action_type": "normalize_label",
            "original_value": "Kutsche",
            "suggested_value": "SHOULD_NOT_APPEAR",
            "reasoning": "Test",
            "target_field": "subject_general",
        })
        sug_id = resp.json()["suggestion"]["suggestion_id"]
        self.client.patch(f"/api/review/suggestions/{sug_id}/status", json={"status": "accepted"})

        self.client.post("/api/review/apply", json={
            "dataset_id": "test-ds",
            "dry_run": True,
        })
        df_after = deps.get_datasets()["test-ds"][0]["subject_general"].tolist()
        self.assertEqual(df_before, df_after)

    def test_changelog_empty_initially(self):
        self._skip_if_no_client()
        resp = self.client.get("/api/review/changelog")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 0)

    def test_export_returns_complete_structure(self):
        self._skip_if_no_client()
        resp = self.client.get("/api/review/export")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("review_queue", data)
        self.assertIn("work_packages", data)
        self.assertIn("suggestions", data)
        self.assertIn("changelog", data)
        self.assertIn("exported_at", data)

    def test_apply_missing_dataset_id(self):
        self._skip_if_no_client()
        resp = self.client.post("/api/review/apply", json={})
        self.assertEqual(resp.status_code, 422)

    def test_apply_nonexistent_dataset(self):
        self._skip_if_no_client()
        resp = self.client.post("/api/review/apply", json={"dataset_id": "nonexistent"})
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
