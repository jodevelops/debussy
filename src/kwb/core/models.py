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
