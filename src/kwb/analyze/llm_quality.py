"""
LLM-gestützte Qualitätsprüfung für GLAM-Metadaten.

Unterstützt vier Analyseebenen:
- cell    : semantische Prüfung einzelner Zellwerte im Feldkontext
- column  : Feldreinheit und typische Fehler einer Spalte
- record  : Kohärenz und Widersprüche innerhalb eines Datensatzes
- dataset : dominante Qualitätsmuster und Work-Package-Kandidaten

Alle LLM-Aufrufe laufen über das AIProvider-Interface (GPUStack / Mock).
Ergebnisse werden in das strukturierte Qualitätsmodell aus Phase 1 integriert.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import pandas as pd

from kwb.ai.batch import BatchReport, process_batch
from kwb.ai.provider import AIProvider
from kwb.core.models import (
    AnalysisProvenance,
    CellFinding,
    ColumnQualityReport,
    DatasetProfile,
    FindingCategory,
    IssueCluster,
    MeasureSummaryEntry,
    QualityAnalysisReport,
    RecordQualityReport,
    Severity,
    WorkPackageCandidate,
)
from kwb.core.utils import try_parse_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LlmQualityCheckMode(str, Enum):
    PILOT = "pilot"  # sample-based, limited number of rows
    FULL = "full"  # all non-empty cells / selected columns


class LlmAnalysisLevel(str, Enum):
    CELL = "cell"
    COLUMN = "column"
    RECORD = "record"
    DATASET = "dataset"


# ---------------------------------------------------------------------------
# LLM-specific result types (richer than Phase-1 CellFinding)
# ---------------------------------------------------------------------------


@dataclass
class LlmCellFinding:
    """A quality finding produced by an LLM for a single cell."""

    record_id: str
    column: str
    value: str
    issue_type: str  # semantic_misplacement | ambiguous | generic | encoding_artifact | review_required
    severity: Severity
    confidence: float
    reasoning: str
    evidence: dict[str, Any] = field(default_factory=dict)
    suggested_target_field: str | None = None
    suggested_action: str = "flag_for_review"  # accept|move_or_review|flag_for_review|correct
    review_required: bool = True
    model_used: str = ""

    def to_cell_finding(self) -> CellFinding:
        """Convert to Phase-1 CellFinding for QualityAnalysisReport integration."""
        category = _ISSUE_TYPE_TO_CATEGORY.get(self.issue_type, FindingCategory.REMEDIATION_CANDIDATE)
        ev = dict(self.evidence)
        if self.suggested_target_field:
            ev["suggested_target_field"] = self.suggested_target_field
        if self.model_used:
            ev["model_used"] = self.model_used
        return CellFinding(
            record_id=self.record_id,
            column=self.column,
            value=self.value,
            severity=self.severity,
            category=category,
            message=self.reasoning,
            confidence=self.confidence,
            reasoning=self.reasoning,
            evidence=ev,
            suggested_action=self.suggested_action,
            review_required=self.review_required,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "column": self.column,
            "value": self.value,
            "issue_type": self.issue_type,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "evidence": self.evidence,
            "suggested_target_field": self.suggested_target_field,
            "suggested_action": self.suggested_action,
            "review_required": self.review_required,
            "model_used": self.model_used,
        }


@dataclass
class LlmColumnReport:
    """Field-purity assessment for a single column produced by an LLM."""

    column: str
    field_semantics: str
    field_purity_score: float  # 0.0–100.0
    dominant_issue_types: list[str] = field(default_factory=list)
    typical_problems: list[str] = field(default_factory=list)
    affected_value_examples: list[str] = field(default_factory=list)
    suggested_action: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    review_required: bool = False
    model_used: str = ""

    def to_column_quality_report(self) -> ColumnQualityReport:
        """Convert to Phase-1 ColumnQualityReport."""
        return ColumnQualityReport(
            column=self.column,
            measure_summary={
                "semantic_correctness": MeasureSummaryEntry(
                    score=int(self.field_purity_score),
                    confidence=self.confidence,
                    reasoning=self.reasoning,
                )
            },
            evidence={
                "dominant_issue_types": self.dominant_issue_types,
                "typical_problems": self.typical_problems,
                "affected_value_examples": self.affected_value_examples,
                "model_used": self.model_used,
            },
            suggested_action=self.suggested_action or None,
            review_required=self.review_required,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "field_semantics": self.field_semantics,
            "field_purity_score": self.field_purity_score,
            "dominant_issue_types": self.dominant_issue_types,
            "typical_problems": self.typical_problems,
            "affected_value_examples": self.affected_value_examples,
            "suggested_action": self.suggested_action,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "review_required": self.review_required,
            "model_used": self.model_used,
        }


@dataclass
class LlmRecordReport:
    """Cross-field coherence report for a single record produced by an LLM."""

    record_id: str
    severity: Severity
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""
    review_required: bool = False
    model_used: str = ""

    def to_record_quality_report(self) -> RecordQualityReport:
        """Convert to Phase-1 RecordQualityReport."""
        issues = [c.get("description", "") for c in self.conflicts if c.get("description")]
        return RecordQualityReport(
            record_id=self.record_id,
            severity=self.severity,
            issues=issues,
            confidence=self.confidence,
            reasoning=self.reasoning,
            review_required=self.review_required,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "severity": self.severity.value,
            "conflicts": self.conflicts,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "review_required": self.review_required,
            "model_used": self.model_used,
        }


@dataclass
class LlmDatasetReport:
    """Dataset-level aggregation of dominant quality patterns."""

    dominant_error_families: list[str] = field(default_factory=list)
    affected_columns: list[str] = field(default_factory=list)
    issue_clusters: list[dict[str, Any]] = field(default_factory=list)
    work_package_candidates: list[dict[str, Any]] = field(default_factory=list)
    risk_summary: str = ""
    confidence: float = 0.0
    model_used: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dominant_error_families": self.dominant_error_families,
            "affected_columns": self.affected_columns,
            "issue_clusters": self.issue_clusters,
            "work_package_candidates": self.work_package_candidates,
            "risk_summary": self.risk_summary,
            "confidence": self.confidence,
            "model_used": self.model_used,
        }


@dataclass
class LlmQualityReport:
    """
    Top-level result of an LLM-assisted quality analysis run.

    Contains both LLM-specific structured findings and a method to produce a
    Phase-1 compatible QualityAnalysisReport.
    """

    mode: LlmQualityCheckMode
    levels: list[LlmAnalysisLevel]
    model_used: str
    analyzed_columns: list[str]
    sample_size: int | None  # None = full mode
    cell_findings: list[LlmCellFinding] = field(default_factory=list)
    column_reports: list[LlmColumnReport] = field(default_factory=list)
    record_reports: list[LlmRecordReport] = field(default_factory=list)
    dataset_report: LlmDatasetReport | None = None
    batch_report_summary: dict[str, Any] = field(default_factory=dict)
    analyzed_at: str = ""
    dataset_profile: DatasetProfile | None = None

    def to_quality_analysis_report(self) -> QualityAnalysisReport:
        """Integrate LLM findings into the structured Phase-1 QualityAnalysisReport."""
        cell_findings_p1 = [f.to_cell_finding() for f in self.cell_findings]

        # Column reports: merge LLM reports with any existing columns
        col_reports_p1 = [r.to_column_quality_report() for r in self.column_reports]

        # Record reports
        rec_reports_p1 = [r.to_record_quality_report() for r in self.record_reports]

        # Issue clusters from dataset report
        clusters_p1: list[IssueCluster] = []
        wps_p1: list[WorkPackageCandidate] = []
        if self.dataset_report:
            for i, cl in enumerate(self.dataset_report.issue_clusters):
                clusters_p1.append(
                    IssueCluster(
                        cluster_id=f"llm-cluster-{i}",
                        label=cl.get("label", f"Cluster {i}"),
                        category=FindingCategory.FIELD_MISUSE,
                        affected_columns=cl.get("affected_columns", []),
                        affected_records_count=cl.get("count", 0),
                        severity=_SEVERITY_MAP.get(cl.get("severity", "warning"), Severity.WARNING),
                        suggested_action=cl.get("suggested_action"),
                    )
                )
            for wp in self.dataset_report.work_package_candidates:
                wps_p1.append(
                    WorkPackageCandidate(
                        title=wp.get("title", ""),
                        description=wp.get("description", ""),
                        priority=_SEVERITY_MAP.get(wp.get("priority", "warning"), Severity.WARNING),
                        affected_columns=wp.get("affected_columns", []),
                        estimated_records=wp.get("estimated_records", 0),
                        action_type=wp.get("action_type", "review"),
                    )
                )

        provenance = AnalysisProvenance(
            analyzed_at=self.analyzed_at or _now_iso(),
            analyzer_version="0.5.2",
            analysis_mode="llm_assisted",
            source_name=self.dataset_profile.source_name if self.dataset_profile else "",
        )

        return QualityAnalysisReport(
            dataset_profiles=[self.dataset_profile] if self.dataset_profile else [],
            quality_measures=[],
            column_reports=col_reports_p1,
            record_reports=rec_reports_p1,
            cell_findings=cell_findings_p1,
            issue_clusters=clusters_p1,
            work_package_candidates=wps_p1,
            analysis_provenance=provenance,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "levels": [lv.value for lv in self.levels],
            "model_used": self.model_used,
            "analyzed_columns": self.analyzed_columns,
            "sample_size": self.sample_size,
            "cell_findings": [f.to_dict() for f in self.cell_findings],
            "column_reports": [r.to_dict() for r in self.column_reports],
            "record_reports": [r.to_dict() for r in self.record_reports],
            "dataset_report": self.dataset_report.to_dict() if self.dataset_report else None,
            "batch_report_summary": self.batch_report_summary,
            "analyzed_at": self.analyzed_at,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ISSUE_TYPE_TO_CATEGORY: dict[str, FindingCategory] = {
    "semantic_misplacement": FindingCategory.FIELD_MISUSE,
    "ambiguous": FindingCategory.AMBIGUOUS_VALUE,
    "generic": FindingCategory.LOW_INFORMATION_VALUE,
    "encoding_artifact": FindingCategory.ENCODING_ISSUES,
    "review_required": FindingCategory.REMEDIATION_CANDIDATE,
    "cross_field_conflict": FindingCategory.CROSS_FIELD_CONFLICT,
}

def _safe_float(value, default: float = 0.5) -> float:
    """Convert *value* to float, returning *default* on any parse error."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


_SEVERITY_MAP: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "warning": Severity.WARNING,
    "info": Severity.INFO,
    "ok": Severity.INFO,
}

# Built-in field semantics for common GLAM metadata field names
_FIELD_SEMANTICS: dict[str, str] = {
    "location_place_name": "Benannter geografischer Ort (Stadt, Dorf, Region, Land)",
    "location": "Geografischer Ort oder Adresse",
    "place": "Geografischer Ort",
    "creator": "Person oder Organisation, die das Objekt erschaffen hat",
    "author": "Autor oder Urheber des Werks",
    "date": "Datum oder Datumsbereich",
    "date_created": "Entstehungsdatum des Objekts",
    "date_issued": "Herausgabedatum",
    "subject": "Thematischer Sachbegriff oder Klassifikationsterm",
    "subject_general": "Allgemeiner Sachbegriff oder Motiv",
    "title": "Titel des Objekts oder Werks",
    "description": "Freitextbeschreibung des Objekts",
    "identifier": "Eindeutiger Identifikator oder Signatur",
    "type": "Objekttyp oder Materialart",
    "format": "Format, Medium oder Material",
    "language": "Sprachcode oder Sprachname",
    "rights": "Rechtsstatus oder Lizenzangabe",
    "publisher": "Verlag, Institution oder herausgebende Organisation",
    "contributor": "Beitragende Person oder Organisation",
    "source": "Herkunft oder Erwerbungsquelle",
    "relation": "Verwandtes Objekt oder Referenz",
    "coverage": "Geografische oder zeitliche Abdeckung",
    "gnd_id": "GND-Normdaten-Identifier",
    "person_name": "Personenname",
    "organization": "Name einer Organisation oder Institution",
    "technique": "Herstellungstechnik oder Verfahren",
    "material": "Material oder Werkstoff",
    "dimensions": "Abmessungen oder Maße",
    "collection": "Sammlungsname oder -zugehörigkeit",
    "provenance": "Provenienz oder Vorbesitz",
}


def _get_field_semantics(column_name: str, overrides: dict[str, str] | None) -> str:
    """Return expected-semantics description for a column, with fallback."""
    if overrides and column_name in overrides:
        return overrides[column_name]
    col_lower = column_name.lower()
    if col_lower in _FIELD_SEMANTICS:
        return _FIELD_SEMANTICS[col_lower]
    for key, desc in _FIELD_SEMANTICS.items():
        if key in col_lower:
            return desc
    return ""


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and pd.isna(val):
        return ""
    return str(val).strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_id_for_row(row: "pd.Series", id_column: str | None, idx: Any) -> str:
    if id_column and id_column in row.index:
        val = _safe_str(row[id_column])
        if val:
            return val
    return str(idx)


def _batch_report_summary(report: BatchReport) -> dict[str, Any]:
    return {
        "total": report.total,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "success_rate": round(report.success_rate, 3),
        "avg_duration_seconds": round(report.avg_duration, 3),
    }


# ---------------------------------------------------------------------------
# Prompt builders (imported from ai.prompts)
# ---------------------------------------------------------------------------

from kwb.ai.prompts import (  # noqa: E402
    prompt_cell_quality_check,
    prompt_column_quality_check,
    prompt_dataset_quality_summary,
    prompt_record_quality_check,
)


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


def run_llm_quality_check(
    df: pd.DataFrame,
    profile: DatasetProfile,
    provider: AIProvider,
    *,
    columns: list[str] | None = None,
    levels: list[LlmAnalysisLevel] | None = None,
    mode: LlmQualityCheckMode = LlmQualityCheckMode.PILOT,
    model: str | None = None,
    sample_size: int = 50,
    field_semantics: dict[str, str] | None = None,
) -> LlmQualityReport:
    """
    Run an LLM-assisted quality check on a DataFrame.

    Args:
        df: The dataset to analyse.
        profile: DatasetProfile for the dataset.
        provider: AI provider to use for all LLM calls.
        columns: Columns to analyse. None = all non-empty columns.
        levels: Analysis levels to run. None = [cell, column].
        mode: PILOT (sampled) or FULL (all non-empty cells).
        model: Override model name; None = provider default.
        sample_size: Number of rows for pilot mode.
        field_semantics: Map of column → expected-semantics description (user-supplied).

    Returns:
        LlmQualityReport with findings at the requested levels.
    """
    if levels is None:
        levels = [LlmAnalysisLevel.CELL, LlmAnalysisLevel.COLUMN]

    # Determine target columns
    if columns:
        target_columns = [c for c in columns if c in df.columns]
    else:
        target_columns = list(df.columns)
        if profile.id_column and profile.id_column in target_columns:
            target_columns.remove(profile.id_column)

    # Determine working dataframe (sampled or full)
    if mode == LlmQualityCheckMode.PILOT and sample_size < len(df):
        working_df = df.sample(n=sample_size, random_state=42).reset_index(drop=True)
        effective_sample = sample_size
    else:
        working_df = df.reset_index(drop=True)
        effective_sample = None

    model_used = model or provider.config.default_model or ""
    analyzed_at = _now_iso()

    cell_findings: list[LlmCellFinding] = []
    column_reports: list[LlmColumnReport] = []
    record_reports: list[LlmRecordReport] = []
    dataset_report: LlmDatasetReport | None = None
    combined_batch_summary: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Cell-level analysis
    # ------------------------------------------------------------------
    if LlmAnalysisLevel.CELL in levels:
        items: list[dict[str, Any]] = []
        for idx, row in working_df.iterrows():
            rec_id = _record_id_for_row(row, profile.id_column, idx)
            for col in target_columns:
                val = _safe_str(row.get(col))
                if not val:
                    continue
                # Record context: up to 8 other non-empty fields
                ctx = {
                    c: _safe_str(row.get(c))
                    for c in working_df.columns
                    if c != col and _safe_str(row.get(c))
                }
                ctx = dict(list(ctx.items())[:8])
                items.append({
                    "record_id": f"{rec_id}::{col}",
                    "_rec_id": rec_id,
                    "_col": col,
                    "_val": val,
                    "field_name": col,
                    "field_semantics": _get_field_semantics(col, field_semantics),
                    "value": val,
                    "record_context": ctx,
                    "dataset_profile": {
                        "source_name": profile.source_name,
                        "row_count": profile.row_count,
                        "columns": [c.name for c in profile.columns],
                    },
                })

        if items:
            batch = process_batch(
                provider=provider,
                items=items,
                prompt_fn=lambda item: prompt_cell_quality_check(
                    field_name=item["field_name"],
                    field_semantics=item["field_semantics"],
                    value=item["value"],
                    record_context=item["record_context"],
                    dataset_profile=item["dataset_profile"],
                ),
                id_field="record_id",
                model=model,
                max_tokens=512,
            )
            combined_batch_summary["cell"] = _batch_report_summary(batch)

            for res, item in zip(batch.results, items):
                if not res.success or not res.parsed:
                    continue
                parsed = res.parsed
                issue_type = parsed.get("issue_type", "review_required")
                if issue_type == "likely_correct":
                    continue
                sev_raw = parsed.get("severity", "info")
                sev = _SEVERITY_MAP.get(sev_raw, Severity.INFO)
                cell_findings.append(
                    LlmCellFinding(
                        record_id=item["_rec_id"],
                        column=item["_col"],
                        value=item["_val"],
                        issue_type=issue_type,
                        severity=sev,
                        confidence=_safe_float(parsed.get("confidence"), 0.5),
                        reasoning=parsed.get("reasoning", ""),
                        evidence=parsed.get("evidence", {}),
                        suggested_target_field=parsed.get("suggested_target_field"),
                        suggested_action=parsed.get("suggested_action", "flag_for_review"),
                        review_required=bool(parsed.get("review_required", True)),
                        model_used=res.response.model if res.response else model_used,
                    )
                )

    # ------------------------------------------------------------------
    # Column-level analysis
    # ------------------------------------------------------------------
    if LlmAnalysisLevel.COLUMN in levels:
        for col in target_columns:
            vals = working_df[col].dropna().astype(str).str.strip()
            vals = vals[vals != ""].tolist()
            if not vals:
                continue
            semantics = _get_field_semantics(col, field_semantics)
            msgs = prompt_column_quality_check(
                field_name=col,
                field_semantics=semantics,
                sample_values=vals[:50],
                non_empty_count=len(vals),
                total_count=len(working_df),
            )
            try:
                resp = provider.complete(msgs, model=model, max_tokens=1024)
                parsed = try_parse_json(resp.content) or {}
                used_model = resp.model
                column_reports.append(
                    LlmColumnReport(
                        column=col,
                        field_semantics=semantics,
                        field_purity_score=_safe_float(parsed.get("field_purity_score"), 50.0),
                        dominant_issue_types=parsed.get("dominant_issue_types", []),
                        typical_problems=parsed.get("typical_problems", []),
                        affected_value_examples=parsed.get("affected_value_examples", []),
                        suggested_action=parsed.get("suggested_action", ""),
                        confidence=_safe_float(parsed.get("confidence"), 0.5),
                        reasoning=parsed.get("reasoning", ""),
                        review_required=bool(parsed.get("review_required", False)),
                        model_used=used_model,
                    )
                )
            except Exception as exc:
                logger.warning("Column quality check failed for '%s': %s", col, exc)

    # ------------------------------------------------------------------
    # Record-level analysis
    # ------------------------------------------------------------------
    if LlmAnalysisLevel.RECORD in levels:
        rec_items: list[dict[str, Any]] = []
        for idx, row in working_df.iterrows():
            rec_id = _record_id_for_row(row, profile.id_column, idx)
            fields = {
                c: _safe_str(row.get(c))
                for c in target_columns
                if _safe_str(row.get(c))
            }
            if not fields:
                continue
            rec_items.append({"record_id": rec_id, "fields": fields})

        if rec_items:
            batch_rec = process_batch(
                provider=provider,
                items=rec_items,
                prompt_fn=lambda item: prompt_record_quality_check(
                    record_id=item["record_id"],
                    fields=item["fields"],
                ),
                id_field="record_id",
                model=model,
                max_tokens=768,
            )
            combined_batch_summary["record"] = _batch_report_summary(batch_rec)

            for res, item in zip(batch_rec.results, rec_items):
                if not res.success or not res.parsed:
                    continue
                parsed = res.parsed
                sev_raw = parsed.get("severity", "info")
                sev = _SEVERITY_MAP.get(sev_raw, Severity.INFO)
                record_reports.append(
                    LlmRecordReport(
                        record_id=item["record_id"],
                        severity=sev,
                        conflicts=parsed.get("conflicts", []),
                        confidence=_safe_float(parsed.get("overall_confidence"), 0.5),
                        reasoning=parsed.get("reasoning", ""),
                        review_required=bool(parsed.get("review_required", False)),
                        model_used=res.response.model if res.response else model_used,
                    )
                )

    # ------------------------------------------------------------------
    # Dataset-level synthesis
    # ------------------------------------------------------------------
    if LlmAnalysisLevel.DATASET in levels:
        issue_summary = _build_issue_summary(cell_findings, column_reports)
        msgs = prompt_dataset_quality_summary(
            source_name=profile.source_name,
            row_count=profile.row_count,
            column_count=profile.column_count,
            analyzed_columns=target_columns,
            issue_summary=issue_summary,
        )
        try:
            resp = provider.complete(msgs, model=model, max_tokens=1536)
            parsed = try_parse_json(resp.content) or {}
            dataset_report = LlmDatasetReport(
                dominant_error_families=parsed.get("dominant_error_families", []),
                affected_columns=parsed.get("at_risk_columns", []),
                issue_clusters=parsed.get("issue_clusters", []),
                work_package_candidates=parsed.get("work_package_candidates", []),
                risk_summary=parsed.get("risk_summary", ""),
                confidence=_safe_float(parsed.get("confidence"), 0.5),
                model_used=resp.model,
            )
        except Exception as exc:
            logger.warning("Dataset-level quality summary failed: %s", exc)

    return LlmQualityReport(
        mode=mode,
        levels=levels,
        model_used=model_used,
        analyzed_columns=target_columns,
        sample_size=effective_sample,
        cell_findings=cell_findings,
        column_reports=column_reports,
        record_reports=record_reports,
        dataset_report=dataset_report,
        batch_report_summary=combined_batch_summary,
        analyzed_at=analyzed_at,
        dataset_profile=profile,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_issue_summary(
    cell_findings: list[LlmCellFinding],
    column_reports: list[LlmColumnReport],
) -> dict[str, Any]:
    """Build a compact issue summary for the dataset-level prompt."""
    issue_counts: dict[str, int] = {}
    affected_cols: dict[str, int] = {}
    for f in cell_findings:
        issue_counts[f.issue_type] = issue_counts.get(f.issue_type, 0) + 1
        affected_cols[f.column] = affected_cols.get(f.column, 0) + 1

    col_purities = {r.column: r.field_purity_score for r in column_reports}

    return {
        "total_findings": len(cell_findings),
        "issue_type_counts": issue_counts,
        "affected_columns": affected_cols,
        "column_purity_scores": col_purities,
    }
