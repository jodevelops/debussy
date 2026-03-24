"""
Core data models for the Kuratierwerkbank.

These models define the shared vocabulary between all modules.
No module imports from another module — they all speak through these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class FindingCategory(str, Enum):
    MISSING_VALUES = "missing_values"
    DUPLICATE_RECORDS = "duplicate_records"
    ENCODING_ISSUES = "encoding_issues"
    FORMAT_INCONSISTENCY = "format_inconsistency"
    SCHEMA_MISMATCH = "schema_mismatch"
    CLASSIFICATION_INCONSISTENCY = "classification_inconsistency"
    LANGUAGE_MIXING = "language_mixing"
    TERM_VARIANTS = "term_variants"
    FIELD_MISUSE = "field_misuse"
    NORM_DATA_CANDIDATE = "norm_data_candidate"
    GND_MATCH_MISSING = "gnd_match_missing"
    GEO_ENRICHMENT_CANDIDATE = "geo_enrichment_candidate"
    CROSS_FILE_MISMATCH = "cross_file_mismatch"
    ORPHAN_RECORDS = "orphan_records"
    AMBIGUOUS_VALUE = "ambiguous_value"
    LOW_INFORMATION_VALUE = "low_information_value"
    CROSS_FIELD_CONFLICT = "cross_field_conflict"
    PROVENANCE_GAP = "provenance_gap"
    NEAR_DUPLICATE_RECORDS = "near_duplicate_records"
    REMEDIATION_CANDIDATE = "remediation_candidate"


@dataclass
class Finding:
    category: FindingCategory
    severity: Severity
    message: str
    column: str | None = None
    record_ids: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    suggestion: str | None = None

    @property
    def scope(self) -> str:
        n = len(self.record_ids)
        if n == 0:
            return "dataset-level"
        elif n == 1:
            return "single-record"
        return f"{n} records"


@dataclass
class ColumnProfile:
    name: str
    dtype: str
    total_count: int
    non_null_count: int
    unique_count: int
    fill_rate: float
    sample_values: list[str] = field(default_factory=list)
    value_lengths: dict[str, int] = field(default_factory=dict)


@dataclass
class DatasetProfile:
    source_path: str
    source_name: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile] = field(default_factory=list)
    id_column: str | None = None
    encoding_detected: str | None = None
    has_bom: bool = False
    line_ending: str | None = None


@dataclass
class AnalysisReport:
    datasets: list[DatasetProfile] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def findings_by_severity(self) -> dict[Severity, list[Finding]]:
        result: dict[Severity, list[Finding]] = {s: [] for s in Severity}
        for f in self.findings:
            result[f.severity].append(f)
        return result

    @property
    def findings_by_category(self) -> dict[FindingCategory, list[Finding]]:
        result: dict[FindingCategory, list[Finding]] = {}
        for f in self.findings:
            result.setdefault(f.category, []).append(f)
        return result

    quality_measures: QualityMeasureReport | None = field(default=None)


class QualityMeasureKey(str, Enum):
    COMPLETENESS = "completeness"
    UNIQUENESS = "uniqueness"
    STRUCTURAL_VALIDITY = "structural_validity"
    CONSISTENCY = "consistency"
    SEMANTIC_CORRECTNESS = "semantic_correctness"
    NORMALIZATION = "normalization"
    CLARITY = "clarity"
    CROSS_FIELD_COHERENCE = "cross_field_coherence"
    PROVENANCE = "provenance"
    FITNESS_FOR_USE = "fitness_for_use"
    RISK_SEVERITY = "risk_severity"
    ACTIONABILITY = "actionability"


class QualityStatus(str, Enum):
    GOOD = "good"
    NEEDS_REVIEW = "needs_review"
    CRITICAL = "critical"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class QualityMeasureSummary:
    measure: QualityMeasureKey
    score: int | None
    status: QualityStatus
    summary: str
    mapped_finding_categories: list[str]
    evidence_count: int
    top_examples: list[dict[str, Any]] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "measure": self.measure.value,
            "score": self.score,
            "status": self.status.value,
            "summary": self.summary,
            "mapped_finding_categories": self.mapped_finding_categories,
            "evidence_count": self.evidence_count,
            "top_examples": self.top_examples,
            "recommended_actions": self.recommended_actions,
        }


@dataclass
class QualityMeasureReport:
    measures: list[QualityMeasureSummary] = field(default_factory=list)

    def by_key(self, key: QualityMeasureKey) -> QualityMeasureSummary | None:
        for m in self.measures:
            if m.measure == key:
                return m
        return None

    def to_dict_list(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.measures]


# ---------------------------------------------------------------------------
# Structured Quality Analysis Report (Phase 1)
# ---------------------------------------------------------------------------


@dataclass
class MeasureSummaryEntry:
    """Per-measure summary for a single column."""

    score: int | None
    confidence: float | None
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


@dataclass
class ColumnQualityReport:
    """Quality report for a single dataset column.

    ``source`` identifies which dataset this column belongs to, enabling
    distinct reports for same-named columns from different datasets.
    """

    column: str
    source: str = ""
    measure_summary: dict[str, MeasureSummaryEntry] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    suggested_action: str | None = None
    review_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "source": self.source,
            "measure_summary": {k: v.to_dict() for k, v in self.measure_summary.items()},
            "evidence": self.evidence,
            "suggested_action": self.suggested_action,
            "review_required": self.review_required,
        }


@dataclass
class RecordQualityReport:
    """Quality report for a single dataset record.

    ``source`` identifies which dataset this record belongs to, preventing
    same-ID records from different datasets from being conflated.
    """

    record_id: str
    source: str = ""
    severity: Severity | None = None
    issues: list[str] = field(default_factory=list)
    confidence: float | None = None
    reasoning: str = ""
    review_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source": self.source,
            "severity": self.severity.value if self.severity else None,
            "issues": self.issues,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "review_required": self.review_required,
        }


@dataclass
class CellFinding:
    """A quality finding at the individual cell level (record × column)."""

    record_id: str
    column: str
    value: str | None = None
    severity: Severity = Severity.INFO
    category: FindingCategory = FindingCategory.MISSING_VALUES
    message: str = ""
    confidence: float | None = None
    reasoning: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    suggested_action: str | None = None
    review_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "column": self.column,
            "value": self.value,
            "severity": self.severity.value,
            "category": self.category.value,
            "message": self.message,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "evidence": self.evidence,
            "suggested_action": self.suggested_action,
            "review_required": self.review_required,
        }


@dataclass
class IssueCluster:
    """A group of related quality issues across columns or records."""

    cluster_id: str
    label: str
    category: FindingCategory
    affected_columns: list[str] = field(default_factory=list)
    affected_records_count: int = 0
    severity: Severity = Severity.INFO
    suggested_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "label": self.label,
            "category": self.category.value,
            "affected_columns": self.affected_columns,
            "affected_records_count": self.affected_records_count,
            "severity": self.severity.value,
            "suggested_action": self.suggested_action,
        }


@dataclass
class WorkPackageCandidate:
    """An actionable work package derived from issue clusters."""

    title: str
    description: str
    priority: Severity
    affected_columns: list[str] = field(default_factory=list)
    estimated_records: int = 0
    action_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "priority": self.priority.value,
            "affected_columns": self.affected_columns,
            "estimated_records": self.estimated_records,
            "action_type": self.action_type,
        }


@dataclass
class AnalysisProvenance:
    """Metadata describing how and when a quality analysis was performed."""

    analyzed_at: str
    analyzer_version: str = "0.5.2"
    analysis_mode: str = "rule_based"  # "rule_based" | "llm_assisted" | "hybrid"
    source_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzed_at": self.analyzed_at,
            "analyzer_version": self.analyzer_version,
            "analysis_mode": self.analysis_mode,
            "source_name": self.source_name,
        }


@dataclass
class QualityAnalysisReport:
    """
    Structured primary format for data quality analysis.

    This is the machine-readable, hierarchical quality report that serves as
    the single source of truth for all downstream rendering (Markdown, GUI,
    JSON export).  Markdown and other output formats are derived from this
    structure rather than the other way around.

    ``dataset_profiles`` holds metadata for *all* analysed datasets so that
    multi-file analyses (cross-file linkage, orphan checks) are fully
    represented without silently dropping files after the first one.
    """

    dataset_profiles: list[DatasetProfile] = field(default_factory=list)
    quality_measures: list[dict[str, Any]] = field(default_factory=list)
    column_reports: list[ColumnQualityReport] = field(default_factory=list)
    record_reports: list[RecordQualityReport] = field(default_factory=list)
    cell_findings: list[CellFinding] = field(default_factory=list)
    issue_clusters: list[IssueCluster] = field(default_factory=list)
    work_package_candidates: list[WorkPackageCandidate] = field(default_factory=list)
    analysis_provenance: AnalysisProvenance | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_profiles": [
                {
                    "source_name": ds.source_name,
                    "row_count": ds.row_count,
                    "column_count": ds.column_count,
                }
                for ds in self.dataset_profiles
            ],
            "quality_measures": self.quality_measures,
            "column_reports": [r.to_dict() for r in self.column_reports],
            "record_reports": [r.to_dict() for r in self.record_reports],
            "cell_findings": [f.to_dict() for f in self.cell_findings],
            "issue_clusters": [c.to_dict() for c in self.issue_clusters],
            "work_package_candidates": [w.to_dict() for w in self.work_package_candidates],
            "analysis_provenance": self.analysis_provenance.to_dict()
            if self.analysis_provenance
            else None,
        }
