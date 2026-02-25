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
    """How urgent is a finding?"""
    CRITICAL = "critical"   # Blocks downstream use (e.g., missing record_id)
    WARNING = "warning"     # Degrades quality (e.g., inconsistent encoding)
    INFO = "info"           # Opportunity for improvement (e.g., enrichment candidate)


class FindingCategory(str, Enum):
    """What kind of problem or opportunity was found?"""
    # Structural
    MISSING_VALUES = "missing_values"
    DUPLICATE_RECORDS = "duplicate_records"
    ENCODING_ISSUES = "encoding_issues"
    FORMAT_INCONSISTENCY = "format_inconsistency"
    SCHEMA_MISMATCH = "schema_mismatch"

    # Semantic
    CLASSIFICATION_INCONSISTENCY = "classification_inconsistency"
    LANGUAGE_MIXING = "language_mixing"
    TERM_VARIANTS = "term_variants"
    FIELD_MISUSE = "field_misuse"

    # Enrichment opportunities
    NORM_DATA_CANDIDATE = "norm_data_candidate"
    GND_MATCH_MISSING = "gnd_match_missing"
    GEO_ENRICHMENT_CANDIDATE = "geo_enrichment_candidate"

    # Data linkage
    CROSS_FILE_MISMATCH = "cross_file_mismatch"
    ORPHAN_RECORDS = "orphan_records"


@dataclass
class Finding:
    """A single observation about the data — the atomic unit of analysis."""
    category: FindingCategory
    severity: Severity
    message: str
    column: str | None = None
    record_ids: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    suggestion: str | None = None

    @property
    def scope(self) -> str:
        """How many records are affected?"""
        n = len(self.record_ids)
        if n == 0:
            return "dataset-level"
        elif n == 1:
            return "single-record"
        else:
            return f"{n} records"


@dataclass
class ColumnProfile:
    """Statistical profile of a single column."""
    name: str
    dtype: str
    total_count: int
    non_null_count: int
    unique_count: int
    fill_rate: float  # 0.0 to 1.0
    sample_values: list[str] = field(default_factory=list)
    value_lengths: dict[str, int] = field(default_factory=dict)  # min, max, mean


@dataclass
class DatasetProfile:
    """Overview of a single ingested dataset (one CSV file)."""
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
    """The complete output of an analysis run across one or more datasets."""
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
