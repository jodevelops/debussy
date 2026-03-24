"""
Structured quality analysis report builder.

Transforms an AnalysisReport (rule-based findings + quality measures) into a
QualityAnalysisReport — the structured primary format for all downstream
rendering (Markdown, GUI, JSON export).

Phase 1: rule-based findings only.
Phase 2 (planned): LLM-based cell / field / record checks enrich the same
structure with higher-confidence, semantically richer entries.
"""

from __future__ import annotations

from datetime import datetime, timezone

from kwb.core.models import (
    AnalysisReport,
    AnalysisProvenance,
    CellFinding,
    ColumnQualityReport,
    FindingCategory,
    IssueCluster,
    MeasureSummaryEntry,
    QualityAnalysisReport,
    RecordQualityReport,
    Severity,
    WorkPackageCandidate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}

_CATEGORY_ACTION_TEMPLATES: dict[FindingCategory, str] = {
    FindingCategory.MISSING_VALUES: "Fehlende Werte in betroffenen Spalten ergänzen",
    FindingCategory.DUPLICATE_RECORDS: "Duplikate identifizieren und bereinigen",
    FindingCategory.ENCODING_ISSUES: "Encoding-Artefakte durch UTF-8-Standardisierung beheben",
    FindingCategory.FORMAT_INCONSISTENCY: "Delimiter- und Whitespace-Inkonsistenzen korrigieren",
    FindingCategory.SCHEMA_MISMATCH: "Schema-Abweichungen prüfen und Pflichtfelder ergänzen",
    FindingCategory.TERM_VARIANTS: "Term-Varianten durch kontrolliertes Vokabular vereinheitlichen",
    FindingCategory.CLASSIFICATION_INCONSISTENCY: "Klassifikationswerte anhand von Normdaten verifizieren",
    FindingCategory.GND_MATCH_MISSING: "GND-Normdatenverknüpfung für betroffene Spalten ergänzen",
    FindingCategory.ORPHAN_RECORDS: "Verwaiste Records auf Verknüpfungsfehler prüfen",
    FindingCategory.CROSS_FIELD_CONFLICT: "Widersprüchliche Feldwerte identifizieren und bereinigen",
    FindingCategory.PROVENANCE_GAP: "Fehlende Herkunftsnachweise durch Quellenangaben ergänzen",
    FindingCategory.NEAR_DUPLICATE_RECORDS: "Near-Duplicate-Kandidaten manuell prüfen",
    FindingCategory.AMBIGUOUS_VALUE: "Mehrdeutige Werte durch Kontextzusätze präzisieren",
    FindingCategory.LOW_INFORMATION_VALUE: "Felder mit niedrigem Informationswert anreichern",
    FindingCategory.REMEDIATION_CANDIDATE: "Automatisch behebbare Findings priorisieren",
    FindingCategory.NORM_DATA_CANDIDATE: "Normalisierungskandidaten in standardisiertes Vokabular überführen",
    FindingCategory.GEO_ENRICHMENT_CANDIDATE: "Geografische Normdaten (Geonames) anreichern",
    FindingCategory.CROSS_FILE_MISMATCH: "Datei-übergreifende Verknüpfungen validieren",
    FindingCategory.LANGUAGE_MIXING: "Sprachmischungen in Metadatenfeldern bereinigen",
    FindingCategory.FIELD_MISUSE: "Fehlplatzierte Werte in korrekte Felder verschieben",
}


def _highest_severity(severities: list[Severity]) -> Severity:
    return min(severities, key=lambda s: _SEVERITY_ORDER[s], default=Severity.INFO)


# ---------------------------------------------------------------------------
# Column report builder
# ---------------------------------------------------------------------------


def _build_column_reports(report: AnalysisReport) -> list[ColumnQualityReport]:
    """Build per-column quality reports from findings and dataset profiles."""
    # Collect column metadata from dataset profiles
    col_meta: dict[str, dict] = {}
    for ds in report.datasets:
        for col in ds.columns:
            col_meta[col.name] = {
                "fill_rate": col.fill_rate,
                "unique_count": col.unique_count,
                "dtype": col.dtype,
            }

    # Group findings by column
    findings_by_col: dict[str, list] = {}
    for f in report.findings:
        if f.column:
            findings_by_col.setdefault(f.column, []).append(f)

    # Also include columns from metadata that have no findings
    all_columns = set(col_meta.keys()) | set(findings_by_col.keys())

    column_reports: list[ColumnQualityReport] = []
    for col_name in sorted(all_columns):
        col_findings = findings_by_col.get(col_name, [])
        meta = col_meta.get(col_name, {})

        # Derive measure summaries from findings for this column
        measure_summary: dict[str, MeasureSummaryEntry] = {}

        completeness_score: int | None = None
        if "fill_rate" in meta:
            completeness_score = round(meta["fill_rate"] * 100)
        measure_summary["completeness"] = MeasureSummaryEntry(
            score=completeness_score,
            confidence=None,
            reasoning="",
        )

        # semantic_correctness placeholder — will be enriched in Phase 2
        measure_summary["semantic_correctness"] = MeasureSummaryEntry(
            score=None,
            confidence=None,
            reasoning="",
        )

        evidence: dict = {}
        if "fill_rate" in meta:
            evidence["fill_rate"] = meta["fill_rate"]
        if "unique_count" in meta:
            evidence["unique_count"] = meta["unique_count"]
        if "dtype" in meta:
            evidence["dtype"] = meta["dtype"]

        # Determine suggested_action and review_required from findings
        suggested_action: str | None = None
        review_required = False
        if col_findings:
            severities = [f.severity for f in col_findings]
            if _highest_severity(severities) in (Severity.CRITICAL, Severity.WARNING):
                review_required = True
            # Pick suggestion from the most severe finding
            for f in sorted(col_findings, key=lambda x: _SEVERITY_ORDER[x.severity]):
                if f.suggestion:
                    suggested_action = f.suggestion
                    break
                # Fall back to category template
                template = _CATEGORY_ACTION_TEMPLATES.get(f.category)
                if template:
                    suggested_action = template
                    break

        column_reports.append(
            ColumnQualityReport(
                column=col_name,
                measure_summary=measure_summary,
                evidence=evidence,
                suggested_action=suggested_action,
                review_required=review_required,
            )
        )

    return column_reports


# ---------------------------------------------------------------------------
# Record report builder
# ---------------------------------------------------------------------------


def _build_record_reports(report: AnalysisReport) -> list[RecordQualityReport]:
    """Derive per-record quality reports from findings that reference record IDs."""
    record_findings: dict[str, list] = {}
    for f in report.findings:
        for rid in f.record_ids:
            record_findings.setdefault(rid, []).append(f)

    record_reports: list[RecordQualityReport] = []
    for record_id, findings in record_findings.items():
        severity = _highest_severity([f.severity for f in findings])
        issues = [f.message for f in findings]
        review_required = severity in (Severity.CRITICAL, Severity.WARNING)

        record_reports.append(
            RecordQualityReport(
                record_id=record_id,
                severity=severity,
                issues=issues,
                confidence=None,
                reasoning="",
                review_required=review_required,
            )
        )

    # Sort by severity then record_id for stable output
    record_reports.sort(key=lambda r: (_SEVERITY_ORDER.get(r.severity, 2), r.record_id))
    return record_reports


# ---------------------------------------------------------------------------
# Cell finding builder
# ---------------------------------------------------------------------------


def _build_cell_findings(report: AnalysisReport) -> list[CellFinding]:
    """Create cell-level findings from findings that target exactly one record and one column."""
    cell_findings: list[CellFinding] = []
    for f in report.findings:
        if f.column and len(f.record_ids) == 1:
            cell_findings.append(
                CellFinding(
                    record_id=f.record_ids[0],
                    column=f.column,
                    value=None,
                    severity=f.severity,
                    category=f.category,
                    message=f.message,
                    confidence=None,
                    reasoning="",
                    evidence=dict(f.evidence),
                    suggested_action=f.suggestion,
                    review_required=f.severity in (Severity.CRITICAL, Severity.WARNING),
                )
            )
    return cell_findings


# ---------------------------------------------------------------------------
# Issue cluster builder
# ---------------------------------------------------------------------------


def _build_issue_clusters(report: AnalysisReport) -> list[IssueCluster]:
    """Group related findings by category into issue clusters."""
    by_cat: dict[FindingCategory, list] = {}
    for f in report.findings:
        by_cat.setdefault(f.category, []).append(f)

    clusters: list[IssueCluster] = []
    for idx, (cat, findings) in enumerate(
        sorted(by_cat.items(), key=lambda x: (_SEVERITY_ORDER[_highest_severity([f.severity for f in x[1]])], x[0].value))
    ):
        cols = sorted({f.column for f in findings if f.column})
        record_ids = {rid for f in findings for rid in f.record_ids}
        severity = _highest_severity([f.severity for f in findings])

        clusters.append(
            IssueCluster(
                cluster_id=f"cluster_{idx:03d}_{cat.value}",
                label=cat.value.replace("_", " ").title(),
                category=cat,
                affected_columns=cols,
                affected_records_count=len(record_ids),
                severity=severity,
                suggested_action=_CATEGORY_ACTION_TEMPLATES.get(cat),
            )
        )

    return clusters


# ---------------------------------------------------------------------------
# Work package candidate builder
# ---------------------------------------------------------------------------


def _build_work_packages(
    clusters: list[IssueCluster],
    report: AnalysisReport,
) -> list[WorkPackageCandidate]:
    """Generate actionable work packages from issue clusters."""
    packages: list[WorkPackageCandidate] = []

    for cluster in clusters:
        # Only create work packages for WARNING/CRITICAL clusters
        if cluster.severity == Severity.INFO:
            continue

        col_hint = (
            f" in {', '.join(cluster.affected_columns[:3])}"
            + (" u.a." if len(cluster.affected_columns) > 3 else "")
            if cluster.affected_columns
            else ""
        )
        description = (
            f"{cluster.label}{col_hint}. "
            f"{cluster.affected_records_count} betroffene Records."
        )

        packages.append(
            WorkPackageCandidate(
                title=cluster.label,
                description=description,
                priority=cluster.severity,
                affected_columns=list(cluster.affected_columns),
                estimated_records=cluster.affected_records_count,
                action_type=cluster.category.value,
            )
        )

    # Sort by priority (CRITICAL first)
    packages.sort(key=lambda p: _SEVERITY_ORDER[p.priority])
    return packages


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_quality_analysis_report(report: AnalysisReport) -> QualityAnalysisReport:
    """
    Transform an AnalysisReport into a QualityAnalysisReport.

    The result is the structured primary format for all downstream rendering.
    Existing rule-based findings are mapped onto the hierarchical structure.
    In Phase 2, LLM-based checks will enrich the same structure.
    """
    # dataset_profile: use first dataset
    dataset_profile = report.datasets[0] if report.datasets else None

    # quality_measures: transform QualityMeasureReport into plain dicts
    quality_measures: list[dict] = []
    if report.quality_measures:
        for m in report.quality_measures.measures:
            quality_measures.append(
                {
                    "measure": m.measure.value,
                    "score": m.score,
                    "status": m.status.value,
                    "confidence": None,  # Phase 1: rule-based, no LLM confidence yet
                    "reasoning": m.summary,
                    "evidence": {
                        "evidence_count": m.evidence_count,
                        "top_examples": m.top_examples,
                        "recommended_actions": m.recommended_actions,
                    },
                }
            )

    column_reports = _build_column_reports(report)
    record_reports = _build_record_reports(report)
    cell_findings = _build_cell_findings(report)
    issue_clusters = _build_issue_clusters(report)
    work_package_candidates = _build_work_packages(issue_clusters, report)

    provenance = AnalysisProvenance(
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        source_name=dataset_profile.source_name if dataset_profile else "",
        analysis_mode="rule_based",
    )

    return QualityAnalysisReport(
        dataset_profile=dataset_profile,
        quality_measures=quality_measures,
        column_reports=column_reports,
        record_reports=record_reports,
        cell_findings=cell_findings,
        issue_clusters=issue_clusters,
        work_package_candidates=work_package_candidates,
        analysis_provenance=provenance,
    )
