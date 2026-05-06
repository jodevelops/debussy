"""
Core data models for the Kuratierwerkbank.

These models define the shared vocabulary between all modules.
No module imports from another module — they all speak through these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypedDict


class Provenance(TypedDict, total=False):
    """
    Canonical provenance shape for all extraction types (CORE-ENH-03).

    All extraction types (EntityReview, CuratedDate, DictionaryEntry,
    AuthorityCandidate, ImageAnalysisResult) expose a uniform `provenance()`
    method that returns this shape. Consumers can rely on the same key set
    regardless of the extraction type.

    Fields use empty strings for absent data (not None) so that downstream
    code can apply uniform string operations without None-checks.
    """
    source: str          # Origin: "manual" | "api" | "llm" | "spacy" | "ner" | "ocr" | "vision_ai" | "gnd" | "wikidata" | "geonames"
    method: str          # Method/algorithm: "rule" | "llm" | "hybrid" | "manual"
    model: str           # AI model name (if applicable, e.g. "qwen3-coder")
    extracted_at: str    # ISO timestamp when extraction happened
    reviewed_at: str     # ISO timestamp when reviewed (if reviewed)
    reviewer: str        # Reviewer username (if reviewed)
    note: str            # Free-text provenance note


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


# ---------------------------------------------------------------------------
# Phase 3 — Review Queues, Work Packages, Remediation
# ---------------------------------------------------------------------------


class ReviewStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_EXPERT_REVIEW = "needs_expert_review"
    APPLIED = "applied"


class RemediationActionType(str, Enum):
    MOVE_VALUE_TO_FIELD = "move_value_to_field"
    SPLIT_MULTI_VALUE = "split_multi_value"
    NORMALIZE_LABEL = "normalize_label"
    FLAG_FOR_AUTHORITY_LOOKUP = "flag_for_authority_lookup"
    LEAVE_UNCHANGED_MARK_UNCERTAIN = "leave_unchanged_mark_uncertain"
    APPLY_SUGGESTED_VALUE = "apply_suggested_value"


@dataclass
class ReviewItem:
    """A single quality finding ready for curatorial review."""

    item_id: str
    source: str
    record_id: str | None
    column: str | None
    original_value: str | None
    category: FindingCategory
    severity: Severity
    confidence: float | None
    message: str
    reasoning: str
    suggested_action: str | None
    status: ReviewStatus = ReviewStatus.PENDING
    reviewer: str | None = None
    reviewed_at: str | None = None
    source_issue_ids: list[str] = field(default_factory=list)
    is_ai_based: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "source": self.source,
            "record_id": self.record_id,
            "column": self.column,
            "original_value": self.original_value,
            "category": self.category.value,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "message": self.message,
            "reasoning": self.reasoning,
            "suggested_action": self.suggested_action,
            "status": self.status.value,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "source_issue_ids": self.source_issue_ids,
            "is_ai_based": self.is_ai_based,
        }


@dataclass
class ReviewDecision:
    """A curatorial decision on a ReviewItem."""

    item_id: str
    decision: ReviewStatus
    reviewed_at: str
    reviewer: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "decision": self.decision.value,
            "reviewed_at": self.reviewed_at,
            "reviewer": self.reviewer,
            "note": self.note,
        }


@dataclass
class WorkPackage:
    """An actionable work package bundling related quality findings."""

    package_id: str
    title: str
    description: str
    scope: str
    issue_family: str
    priority: Severity
    affected_columns: list[str]
    estimated_records: int
    action_type: str
    automation_potential: str  # "high" | "medium" | "low"
    recommended_strategy: str
    source_cluster_ids: list[str] = field(default_factory=list)
    item_ids: list[str] = field(default_factory=list)
    status: ReviewStatus = ReviewStatus.PENDING
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "title": self.title,
            "description": self.description,
            "scope": self.scope,
            "issue_family": self.issue_family,
            "priority": self.priority.value,
            "affected_columns": self.affected_columns,
            "estimated_records": self.estimated_records,
            "action_type": self.action_type,
            "automation_potential": self.automation_potential,
            "recommended_strategy": self.recommended_strategy,
            "source_cluster_ids": self.source_cluster_ids,
            "item_ids": self.item_ids,
            "status": self.status.value,
            "created_at": self.created_at,
        }


@dataclass
class RemediationSuggestion:
    """A structured suggestion for correcting a specific quality issue."""

    suggestion_id: str
    action_type: RemediationActionType
    original_value: str | None
    suggested_value: str | None
    reasoning: str
    item_id: str | None = None
    package_id: str | None = None
    target_field: str | None = None
    confidence: float | None = None
    status: ReviewStatus = ReviewStatus.PENDING
    is_ai_based: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "action_type": self.action_type.value,
            "original_value": self.original_value,
            "suggested_value": self.suggested_value,
            "reasoning": self.reasoning,
            "item_id": self.item_id,
            "package_id": self.package_id,
            "target_field": self.target_field,
            "confidence": self.confidence,
            "status": self.status.value,
            "is_ai_based": self.is_ai_based,
        }


@dataclass
class AppliedChangeLog:
    """An immutable log entry for a change applied to dataset metadata."""

    change_id: str
    dataset_id: str
    record_id: str
    column: str
    original_value: str | None
    new_value: str | None
    action_type: RemediationActionType
    applied_at: str
    reviewer: str | None = None
    suggestion_id: str | None = None
    item_id: str | None = None
    package_id: str | None = None
    is_ai_based: bool = False
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "dataset_id": self.dataset_id,
            "record_id": self.record_id,
            "column": self.column,
            "original_value": self.original_value,
            "new_value": self.new_value,
            "action_type": self.action_type.value,
            "applied_at": self.applied_at,
            "reviewer": self.reviewer,
            "suggestion_id": self.suggestion_id,
            "item_id": self.item_id,
            "package_id": self.package_id,
            "is_ai_based": self.is_ai_based,
            "note": self.note,
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
