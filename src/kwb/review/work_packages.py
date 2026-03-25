"""
Work Package generation from IssueCluster and ReviewQueue.

Entry point:
    generate_work_packages(report, queue)  →  list[WorkPackage]

Logic:
  - Each IssueCluster with WARNING/CRITICAL severity becomes a WorkPackage candidate.
  - Additional heuristics set automation_potential and recommended_strategy.
  - ReviewItems belonging to the cluster are linked via item_ids.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from kwb.core.models import (
    FindingCategory,
    IssueCluster,
    QualityAnalysisReport,
    ReviewStatus,
    Severity,
    WorkPackage,
)
from kwb.review.queue import ReviewQueue


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Automation potential heuristics
# ---------------------------------------------------------------------------

_HIGH_AUTOMATION_CATEGORIES = {
    FindingCategory.MISSING_VALUES,
    FindingCategory.ENCODING_ISSUES,
    FindingCategory.FORMAT_INCONSISTENCY,
    FindingCategory.DUPLICATE_RECORDS,
    FindingCategory.NEAR_DUPLICATE_RECORDS,
}

_MEDIUM_AUTOMATION_CATEGORIES = {
    FindingCategory.TERM_VARIANTS,
    FindingCategory.NORM_DATA_CANDIDATE,
    FindingCategory.GND_MATCH_MISSING,
    FindingCategory.GEO_ENRICHMENT_CANDIDATE,
    FindingCategory.REMEDIATION_CANDIDATE,
}

_STRATEGY_MAP: dict[FindingCategory, str] = {
    FindingCategory.MISSING_VALUES: "Fehlende Werte ergänzen oder Felder als optional markieren",
    FindingCategory.DUPLICATE_RECORDS: "Duplikate zusammenführen oder löschen",
    FindingCategory.NEAR_DUPLICATE_RECORDS: "Ähnliche Datensätze manuell prüfen und zusammenführen",
    FindingCategory.ENCODING_ISSUES: "Encoding-Artefakte bereinigen (UTF-8 normalisieren)",
    FindingCategory.FORMAT_INCONSISTENCY: "Einheitliches Format erzwingen (Trennzeichen, Leerzeichen)",
    FindingCategory.TERM_VARIANTS: "Varianten auf Vorzugsbenennung normalisieren",
    FindingCategory.FIELD_MISUSE: "Werte in korrekte Zielspalte verschieben",
    FindingCategory.AMBIGUOUS_VALUE: "Ambige Werte einzeln prüfen und klären",
    FindingCategory.CROSS_FIELD_CONFLICT: "Konfligierende Felder gemeinsam prüfen und abstimmen",
    FindingCategory.PROVENANCE_GAP: "Fehlende Provenienzinformationen nacherfassen",
    FindingCategory.GND_MATCH_MISSING: "GND-Normdaten zuordnen (lobid.org)",
    FindingCategory.GEO_ENRICHMENT_CANDIDATE: "Geografische Anreicherung via GeoNames prüfen",
    FindingCategory.NORM_DATA_CANDIDATE: "Normdaten-Kandidaten prüfen und verknüpfen",
    FindingCategory.CLASSIFICATION_INCONSISTENCY: "Klassifikation vereinheitlichen",
    FindingCategory.SCHEMA_MISMATCH: "Schema-Abweichungen bereinigen",
    FindingCategory.LANGUAGE_MIXING: "Sprachmischungen prüfen und trennen",
    FindingCategory.LOW_INFORMATION_VALUE: "Informationsarme Werte prüfen und ggf. löschen",
    FindingCategory.CROSS_FILE_MISMATCH: "Datensatz-übergreifende Inkonsistenzen auflösen",
    FindingCategory.ORPHAN_RECORDS: "Verwaiste Datensätze prüfen und verknüpfen oder löschen",
    FindingCategory.REMEDIATION_CANDIDATE: "Bereinigungsvorschläge prüfen und anwenden",
}

_DEFAULT_STRATEGY = "Befunde manuell prüfen und bereinigen"

_ACTION_TYPE_MAP: dict[FindingCategory, str] = {
    FindingCategory.MISSING_VALUES: "fill_missing",
    FindingCategory.DUPLICATE_RECORDS: "deduplicate",
    FindingCategory.NEAR_DUPLICATE_RECORDS: "review_near_duplicates",
    FindingCategory.ENCODING_ISSUES: "normalize_encoding",
    FindingCategory.FORMAT_INCONSISTENCY: "normalize_format",
    FindingCategory.TERM_VARIANTS: "normalize_label",
    FindingCategory.FIELD_MISUSE: "move_value_to_field",
    FindingCategory.AMBIGUOUS_VALUE: "flag_for_review",
    FindingCategory.GND_MATCH_MISSING: "flag_for_authority_lookup",
    FindingCategory.GEO_ENRICHMENT_CANDIDATE: "flag_for_authority_lookup",
    FindingCategory.NORM_DATA_CANDIDATE: "flag_for_authority_lookup",
    FindingCategory.CROSS_FIELD_CONFLICT: "review_conflict",
    FindingCategory.PROVENANCE_GAP: "fill_missing",
    FindingCategory.REMEDIATION_CANDIDATE: "apply_suggested_value",
}

_DEFAULT_ACTION = "manual_review"


def _automation_potential(category: FindingCategory, severity: Severity) -> str:
    if category in _HIGH_AUTOMATION_CATEGORIES:
        return "high"
    if category in _MEDIUM_AUTOMATION_CATEGORIES:
        return "medium"
    return "low"


def _scope_description(cluster: IssueCluster) -> str:
    cols = ", ".join(cluster.affected_columns) if cluster.affected_columns else "unbekannte Spalten"
    return (
        f"Betrifft {cluster.affected_records_count} Datensätze in Spalten: {cols}. "
        f"Kategorie: {cluster.category.value}."
    )


def generate_work_packages(
    report: QualityAnalysisReport,
    queue: ReviewQueue | None = None,
) -> list[WorkPackage]:
    """Generate WorkPackages from a QualityAnalysisReport.

    Each WARNING/CRITICAL IssueCluster becomes one WorkPackage.
    If a ReviewQueue is provided, linked ReviewItem IDs are collected.
    """
    packages: list[WorkPackage] = []
    now = _now_iso()

    for cluster in report.issue_clusters:
        if cluster.severity == Severity.INFO:
            continue  # INFO clusters don't produce work packages

        # Collect linked ReviewItem IDs from queue
        item_ids: list[str] = []
        if queue is not None:
            for item in queue.filter(category=cluster.category.value):
                if (
                    not item.source_issue_ids
                    or cluster.cluster_id in item.source_issue_ids
                    or (
                        item.column in cluster.affected_columns
                        and item.record_id is None  # cluster-level items
                    )
                ):
                    item_ids.append(item.item_id)

        pkg = WorkPackage(
            package_id=str(uuid.uuid4()),
            title=cluster.label,
            description=cluster.suggested_action or _DEFAULT_STRATEGY,
            scope=_scope_description(cluster),
            issue_family=cluster.category.value,
            priority=cluster.severity,
            affected_columns=list(cluster.affected_columns),
            estimated_records=cluster.affected_records_count,
            action_type=_ACTION_TYPE_MAP.get(cluster.category, _DEFAULT_ACTION),
            automation_potential=_automation_potential(cluster.category, cluster.severity),
            recommended_strategy=_STRATEGY_MAP.get(cluster.category, _DEFAULT_STRATEGY),
            source_cluster_ids=[cluster.cluster_id],
            item_ids=item_ids,
            status=ReviewStatus.PENDING,
            created_at=now,
        )
        packages.append(pkg)

    # Also surface WorkPackageCandidates from the report that have no cluster
    cluster_categories = {c.category for c in report.issue_clusters}
    for wpc in report.work_package_candidates:
        # Avoid duplicating if we already covered this category
        # (WorkPackageCandidates use action_type, not category directly)
        pkg = WorkPackage(
            package_id=str(uuid.uuid4()),
            title=wpc.title,
            description=wpc.description,
            scope=f"Betrifft ~{wpc.estimated_records} Datensätze in: "
            f"{', '.join(wpc.affected_columns)}",
            issue_family=wpc.action_type,
            priority=wpc.priority,
            affected_columns=list(wpc.affected_columns),
            estimated_records=wpc.estimated_records,
            action_type=wpc.action_type,
            automation_potential="medium",
            recommended_strategy=wpc.description,
            source_cluster_ids=[],
            item_ids=[],
            status=ReviewStatus.PENDING,
            created_at=now,
        )
        packages.append(pkg)

    # Sort: CRITICAL first, then by estimated_records descending
    packages.sort(
        key=lambda p: (0 if p.priority == Severity.CRITICAL else 1, -p.estimated_records)
    )
    return packages
