"""
12 harmonized core data-quality measures.

Aggregates existing low-level findings into a stable, stakeholder-facing
reporting layer. The diagnostic FindingCategory model is preserved; this
module builds a summary on top of it.
"""
from __future__ import annotations

from kwb.core.models import (
    AnalysisReport,
    FindingCategory,
    QualityMeasureKey,
    QualityMeasureReport,
    QualityMeasureSummary,
    QualityStatus,
    Severity,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _status_from_score(score: int | None) -> QualityStatus:
    if score is None:
        return QualityStatus.INSUFFICIENT_DATA
    if score >= 80:
        return QualityStatus.GOOD
    if score >= 50:
        return QualityStatus.NEEDS_REVIEW
    return QualityStatus.CRITICAL


def _no_data(key: QualityMeasureKey, cats: list[str]) -> QualityMeasureSummary:
    return QualityMeasureSummary(
        measure=key,
        score=None,
        status=QualityStatus.INSUFFICIENT_DATA,
        summary="Nicht genug Daten für diese Maßzahl.",
        mapped_finding_categories=cats,
        evidence_count=0,
    )


# ---------------------------------------------------------------------------
# Individual measure computations
# ---------------------------------------------------------------------------

def _compute_completeness(report: AnalysisReport) -> QualityMeasureSummary:
    cats = ["missing_values"]
    if not report.datasets:
        return _no_data(QualityMeasureKey.COMPLETENESS, cats)

    all_fill_rates = [col.fill_rate for ds in report.datasets for col in ds.columns]
    score = round(sum(all_fill_rates) / len(all_fill_rates) * 100) if all_fill_rates else None

    findings = report.findings_by_category.get(FindingCategory.MISSING_VALUES, [])
    evidence_count = sum(f.evidence.get("missing_count", 0) for f in findings)

    top_examples = [
        {
            "column": f.column,
            "fill_rate": f.evidence.get("fill_rate", 0),
            "missing_count": f.evidence.get("missing_count", 0),
            "severity": f.severity.value,
        }
        for f in sorted(findings, key=lambda x: x.evidence.get("missing_count", 0), reverse=True)[:3]
        if f.column
    ]

    if score is None:
        summary = "Vollständigkeit konnte nicht berechnet werden."
    elif score >= 80:
        summary = f"Metadaten gut befüllt (Ø {score}% Füllrate)."
    elif score >= 50:
        summary = f"Fehlende Werte in mehreren Spalten (Ø {score}% Füllrate). Überprüfung empfohlen."
    else:
        summary = f"Erhebliche Metadatenlücken (Ø {score}% Füllrate). Dringend überarbeiten."

    actions = []
    if findings:
        actions.append("Pflichtfelder prüfen und fehlende Werte ergänzen")
        if any(f.evidence.get("fill_rate", 1) < 0.1 for f in findings):
            actions.append("Nahezu leere Spalten auf Relevanz prüfen")

    return QualityMeasureSummary(
        measure=QualityMeasureKey.COMPLETENESS,
        score=score,
        status=_status_from_score(score),
        summary=summary,
        mapped_finding_categories=cats,
        evidence_count=evidence_count,
        top_examples=top_examples,
        recommended_actions=actions,
    )


def _compute_uniqueness(report: AnalysisReport) -> QualityMeasureSummary:
    cats = ["duplicate_records", "near_duplicate_records"]
    total_records = report.summary.get("total_records", 0)

    if total_records == 0:
        return _no_data(QualityMeasureKey.UNIQUENESS, cats)

    dup_findings = report.findings_by_category.get(FindingCategory.DUPLICATE_RECORDS, [])
    near_dup_findings = report.findings_by_category.get(FindingCategory.NEAR_DUPLICATE_RECORDS, [])
    dup_count = sum(f.evidence.get("duplicate_row_count", 0) for f in dup_findings)
    near_dup_count = sum(f.evidence.get("near_duplicate_count", len(f.record_ids)) for f in near_dup_findings)

    penalty = (dup_count / total_records * 100) + (near_dup_count / total_records * 50)
    score = max(0, round(100 - penalty)) if (dup_count or near_dup_count) else 100

    if dup_count == 0 and near_dup_count == 0:
        summary = "Keine Duplikate gefunden. Alle Records eindeutig identifizierbar."
    elif dup_count > 0 and near_dup_count > 0:
        summary = (
            f"{dup_count} duplizierte Zeilen ({dup_count / total_records:.1%}), "
            f"{near_dup_count} Near-Duplicate-Kandidaten."
        )
    elif dup_count > 0:
        summary = f"{dup_count} duplizierte Zeilen ({dup_count / total_records:.1%} der Records)."
    else:
        summary = f"{near_dup_count} Near-Duplicate-Kandidaten gefunden. Manuelle Prüfung empfohlen."

    top_examples = [
        {
            "column": f.column,
            "duplicate_count": f.evidence.get("duplicate_row_count", 0),
            "severity": f.severity.value,
            "sample_ids": f.record_ids[:3],
        }
        for f in dup_findings[:3]
    ]

    actions = []
    if dup_findings:
        actions.append("Duplikate identifizieren und zusammenführen oder entfernen")
    if near_dup_findings:
        actions.append("Near-Duplicate-Kandidaten manuell prüfen")

    return QualityMeasureSummary(
        measure=QualityMeasureKey.UNIQUENESS,
        score=score,
        status=_status_from_score(score),
        summary=summary,
        mapped_finding_categories=cats,
        evidence_count=dup_count,
        top_examples=top_examples,
        recommended_actions=actions,
    )


def _compute_structural_validity(report: AnalysisReport) -> QualityMeasureSummary:
    cats = ["encoding_issues", "format_inconsistency", "schema_mismatch"]
    total_columns = report.summary.get("total_columns", 0)

    if total_columns == 0:
        return _no_data(QualityMeasureKey.STRUCTURAL_VALIDITY, cats)

    by_cat = report.findings_by_category
    all_findings = (
        by_cat.get(FindingCategory.ENCODING_ISSUES, [])
        + by_cat.get(FindingCategory.FORMAT_INCONSISTENCY, [])
        + by_cat.get(FindingCategory.SCHEMA_MISMATCH, [])
    )

    penalty = sum(
        20 if f.severity == Severity.CRITICAL else 10 if f.severity == Severity.WARNING else 3
        for f in all_findings
    )
    score = max(0, 100 - penalty)

    if not all_findings:
        summary = "Keine strukturellen Probleme. Encoding und Format konsistent."
    elif score >= 80:
        summary = f"{len(all_findings)} kleinere strukturelle Hinweise, keine kritischen Probleme."
    else:
        summary = f"{len(all_findings)} strukturelle Probleme (Encoding, Format, Schema)."

    top_examples = [
        {"category": f.category.value, "message": f.message, "severity": f.severity.value}
        for f in sorted(all_findings, key=lambda x: (x.severity != Severity.CRITICAL, x.severity != Severity.WARNING))[:3]
    ]

    actions = []
    if by_cat.get(FindingCategory.ENCODING_ISSUES):
        actions.append("Encoding-Artefakte bereinigen (UTF-8 Standardisierung)")
    if by_cat.get(FindingCategory.FORMAT_INCONSISTENCY):
        actions.append("Delimiter-Inkonsistenzen und Whitespace korrigieren")
    if by_cat.get(FindingCategory.SCHEMA_MISMATCH):
        actions.append("Schema-Abweichungen prüfen und Pflichtfelder ergänzen")

    return QualityMeasureSummary(
        measure=QualityMeasureKey.STRUCTURAL_VALIDITY,
        score=score,
        status=_status_from_score(score),
        summary=summary,
        mapped_finding_categories=cats,
        evidence_count=len(all_findings),
        top_examples=top_examples,
        recommended_actions=actions,
    )


def _compute_consistency(report: AnalysisReport) -> QualityMeasureSummary:
    cats = ["term_variants", "format_inconsistency", "classification_inconsistency"]
    total_columns = report.summary.get("total_columns", 0)

    if total_columns == 0:
        return _no_data(QualityMeasureKey.CONSISTENCY, cats)

    by_cat = report.findings_by_category
    tv_findings = by_cat.get(FindingCategory.TERM_VARIANTS, [])
    cls_findings = by_cat.get(FindingCategory.CLASSIFICATION_INCONSISTENCY, [])
    fmt_findings = by_cat.get(FindingCategory.FORMAT_INCONSISTENCY, [])

    variant_groups = sum(f.evidence.get("variant_count", 0) for f in tv_findings)
    fmt_rows = sum(f.evidence.get("both_rows", f.evidence.get("whitespace_count", 0)) for f in fmt_findings)
    penalty = min(80, variant_groups * 5 + len(cls_findings) * 10 + (10 if fmt_findings else 0))
    score = max(0, 100 - penalty)

    if not tv_findings and not cls_findings and not fmt_findings:
        summary = "Werte konsistent. Keine Term-Varianten, Format- oder Klassifikationsinkonsistenzen."
    else:
        parts = []
        if variant_groups:
            parts.append(f"{variant_groups} Term-Variantengruppen")
        if cls_findings:
            parts.append(f"{len(cls_findings)} Klassifikationsinkonsistenzen")
        if fmt_findings:
            parts.append(f"{len(fmt_findings)} Format-Inkonsistenzen")
        summary = ", ".join(parts) + "."

    top_examples = []
    for f in tv_findings[:2]:
        for ex in f.evidence.get("examples", [])[:2]:
            top_examples.append({
                "column": f.column,
                "canonical": ex.get("canonical", ""),
                "forms": ex.get("forms", []),
                "severity": f.severity.value,
            })

    actions = []
    if tv_findings:
        actions.append("Term-Varianten normalisieren (Groß-/Kleinschreibung vereinheitlichen)")
    if cls_findings:
        actions.append("Klassifikationswerte auf kontrolliertes Vokabular prüfen")
    if fmt_findings:
        actions.append("Format-Inkonsistenzen bereinigen")

    return QualityMeasureSummary(
        measure=QualityMeasureKey.CONSISTENCY,
        score=score,
        status=_status_from_score(score),
        summary=summary,
        mapped_finding_categories=cats,
        evidence_count=variant_groups + len(cls_findings) + len(fmt_findings),
        top_examples=top_examples,
        recommended_actions=actions,
    )


def _compute_semantic_correctness(report: AnalysisReport) -> QualityMeasureSummary:
    cats = ["field_misuse", "classification_inconsistency", "ambiguous_value"]

    if not report.datasets:
        return _no_data(QualityMeasureKey.SEMANTIC_CORRECTNESS, cats)

    by_cat = report.findings_by_category
    fm_findings = by_cat.get(FindingCategory.FIELD_MISUSE, [])
    cls_findings = by_cat.get(FindingCategory.CLASSIFICATION_INCONSISTENCY, [])
    amb_findings = by_cat.get(FindingCategory.AMBIGUOUS_VALUE, [])
    all_findings = fm_findings + cls_findings + amb_findings

    if not all_findings:
        score = 75
        summary = "Keine semantischen Probleme aus Strukturanalyse erkannt. KI-Prüfung empfohlen."
    else:
        penalty = min(80, len(fm_findings) * 15 + len(cls_findings) * 10 + len(amb_findings) * 5)
        score = max(0, 100 - penalty)
        summary = (
            f"{len(fm_findings)} Feldzuordnungsprobleme, "
            f"{len(cls_findings)} Klassifikationsfehler, "
            f"{len(amb_findings)} mehrdeutige Werte."
        )

    top_examples = [
        {
            "category": f.category.value,
            "column": f.column,
            "message": f.message,
            "severity": f.severity.value,
        }
        for f in (fm_findings + amb_findings)[:3]
    ]

    actions = []
    if fm_findings:
        actions.append("Fehlplatzierte Werte in korrekte Felder verschieben")
    if cls_findings:
        actions.append("Klassifikationswerte anhand von Normdaten verifizieren")
    if amb_findings:
        actions.append("Mehrdeutige Werte durch Kontextualisierung klären")
    if not all_findings:
        actions.append("Semantische KI-Analyse für tiefere Prüfung durchführen")

    return QualityMeasureSummary(
        measure=QualityMeasureKey.SEMANTIC_CORRECTNESS,
        score=score,
        status=_status_from_score(score),
        summary=summary,
        mapped_finding_categories=cats,
        evidence_count=len(all_findings),
        top_examples=top_examples,
        recommended_actions=actions,
    )


def _compute_normalization(report: AnalysisReport) -> QualityMeasureSummary:
    cats = ["term_variants", "norm_data_candidate", "gnd_match_missing"]

    by_cat = report.findings_by_category
    has_relevant = bool(
        by_cat.get(FindingCategory.TERM_VARIANTS)
        or by_cat.get(FindingCategory.NORM_DATA_CANDIDATE)
        or by_cat.get(FindingCategory.GND_MATCH_MISSING)
    )
    if not report.datasets and not has_relevant:
        return _no_data(QualityMeasureKey.NORMALIZATION, cats)

    tv_findings = by_cat.get(FindingCategory.TERM_VARIANTS, [])
    norm_findings = by_cat.get(FindingCategory.NORM_DATA_CANDIDATE, [])
    gnd_findings = by_cat.get(FindingCategory.GND_MATCH_MISSING, [])

    gnd_coverage: float | None = next(
        (f.evidence["coverage_rate"] for f in gnd_findings if "coverage_rate" in f.evidence),
        None,
    )
    variant_groups = sum(f.evidence.get("variant_count", 0) for f in tv_findings)

    if gnd_coverage is not None:
        score = max(0, round(gnd_coverage * 100) - min(30, variant_groups * 3))
        summary = f"GND-Abdeckung: {gnd_coverage:.1%}. {variant_groups} Term-Variantengruppen."
    elif tv_findings:
        score = max(0, 100 - variant_groups * 5)
        summary = f"{variant_groups} Term-Variantengruppen ohne Normalisierungsreferenz."
    else:
        score = 80
        summary = "Keine GND-Spalten erkannt. Keine Term-Varianten gefunden."

    top_examples = [
        {
            "category": "gnd_match_missing",
            "coverage_rate": f.evidence.get("coverage_rate"),
            "no_match_count": f.evidence.get("no_match_count", 0),
            "severity": f.severity.value,
        }
        for f in gnd_findings[:2]
    ]

    evidence_count = variant_groups + sum(f.evidence.get("no_match_count", 0) for f in gnd_findings)

    actions = []
    if gnd_findings and (gnd_coverage is None or gnd_coverage < 0.8):
        actions.append("GND-Verlinkung vervollständigen (API-Lookup empfohlen)")
    if tv_findings:
        actions.append("Term-Varianten auf Normdaten-Entsprechungen abbilden")
    if norm_findings:
        actions.append("Normalisierungskandidaten in standardisiertes Vokabular überführen")

    return QualityMeasureSummary(
        measure=QualityMeasureKey.NORMALIZATION,
        score=score,
        status=_status_from_score(score),
        summary=summary,
        mapped_finding_categories=cats,
        evidence_count=evidence_count,
        top_examples=top_examples,
        recommended_actions=actions,
    )


def _compute_clarity(report: AnalysisReport) -> QualityMeasureSummary:
    cats = ["low_information_value", "ambiguous_value"]

    if not report.datasets:
        return _no_data(QualityMeasureKey.CLARITY, cats)

    by_cat = report.findings_by_category
    liv_findings = by_cat.get(FindingCategory.LOW_INFORMATION_VALUE, [])
    amb_findings = by_cat.get(FindingCategory.AMBIGUOUS_VALUE, [])
    all_findings = liv_findings + amb_findings

    if not all_findings:
        score = 80
        summary = "Keine Klarheits- oder Interpretierbarkeits-Probleme aus Strukturanalyse erkannt."
    else:
        penalty = min(80, len(liv_findings) * 10 + len(amb_findings) * 5)
        score = max(0, 100 - penalty)
        summary = f"{len(liv_findings)} informationsarme Felder, {len(amb_findings)} mehrdeutige Werte."

    actions = []
    if liv_findings:
        actions.append("Felder mit niedrigem Informationswert anreichern oder entfernen")
    if amb_findings:
        actions.append("Mehrdeutige Werte durch Kontextzusätze präzisieren")
    if not all_findings:
        actions.append("KI-gestützte Klarheitsanalyse für detailliertere Befunde nutzen")

    return QualityMeasureSummary(
        measure=QualityMeasureKey.CLARITY,
        score=score,
        status=_status_from_score(score),
        summary=summary,
        mapped_finding_categories=cats,
        evidence_count=len(all_findings),
        recommended_actions=actions,
    )


def _compute_cross_field_coherence(report: AnalysisReport) -> QualityMeasureSummary:
    cats = ["cross_field_conflict", "cross_file_mismatch", "orphan_records"]

    by_cat = report.findings_by_category
    cfc_findings = by_cat.get(FindingCategory.CROSS_FIELD_CONFLICT, [])
    cfm_findings = by_cat.get(FindingCategory.CROSS_FILE_MISMATCH, [])
    orphan_findings = by_cat.get(FindingCategory.ORPHAN_RECORDS, [])
    all_findings = cfc_findings + cfm_findings + orphan_findings

    if not all_findings and not report.datasets:
        return _no_data(QualityMeasureKey.CROSS_FIELD_COHERENCE, cats)

    orphan_count = sum(f.evidence.get("orphan_count", 0) for f in orphan_findings)
    penalty = min(80, len(cfc_findings) * 15 + len(orphan_findings) * 10 + len(cfm_findings) * 5)
    score = max(0, 100 - penalty)

    if not all_findings:
        summary = "Keine Feldzusammenhangsprobleme oder Verknüpfungsfehler erkannt."
    else:
        parts = []
        if cfc_findings:
            parts.append(f"{len(cfc_findings)} Feldkonflikte")
        if orphan_findings:
            parts.append(f"{orphan_count} verwaiste Records")
        if cfm_findings:
            parts.append(f"{len(cfm_findings)} Datei-Verknüpfungsprobleme")
        summary = ", ".join(parts) + " gefunden."

    top_examples = [
        {
            "category": "orphan_records",
            "message": f.message,
            "orphan_count": f.evidence.get("orphan_count", 0),
            "severity": f.severity.value,
        }
        for f in orphan_findings[:2]
    ]

    actions = []
    if orphan_findings:
        actions.append("Verwaiste Records auf Verknüpfungsfehler prüfen und korrigieren")
    if cfc_findings:
        actions.append("Widersprüchliche Feldwerte identifizieren und bereinigen")
    if cfm_findings:
        actions.append("Datei-übergreifende Verknüpfungen validieren")

    return QualityMeasureSummary(
        measure=QualityMeasureKey.CROSS_FIELD_COHERENCE,
        score=score,
        status=_status_from_score(score),
        summary=summary,
        mapped_finding_categories=cats,
        evidence_count=orphan_count + len(cfc_findings),
        top_examples=top_examples,
        recommended_actions=actions,
    )


def _compute_provenance(report: AnalysisReport) -> QualityMeasureSummary:
    cats = ["provenance_gap", "gnd_match_missing", "geo_enrichment_candidate"]

    by_cat = report.findings_by_category
    pg_findings = by_cat.get(FindingCategory.PROVENANCE_GAP, [])
    has_relevant = bool(
        pg_findings
        or by_cat.get(FindingCategory.GND_MATCH_MISSING)
        or by_cat.get(FindingCategory.GEO_ENRICHMENT_CANDIDATE)
    )
    if not report.datasets and not has_relevant:
        return _no_data(QualityMeasureKey.PROVENANCE, cats)
    gnd_findings = by_cat.get(FindingCategory.GND_MATCH_MISSING, [])
    geo_findings = by_cat.get(FindingCategory.GEO_ENRICHMENT_CANDIDATE, [])

    gnd_coverage: float | None = next(
        (f.evidence["coverage_rate"] for f in gnd_findings if "coverage_rate" in f.evidence),
        None,
    )

    if gnd_coverage is not None:
        score = max(0, round(gnd_coverage * 100) - len(pg_findings) * 10)
        summary = f"Normdaten-Abdeckung: {gnd_coverage:.1%}. {len(pg_findings)} Provenienzlücken."
    elif pg_findings:
        score = max(0, 100 - len(pg_findings) * 15)
        summary = f"{len(pg_findings)} fehlende Herkunftsnachweise."
    else:
        score = 70
        summary = "Keine Normdatenspalten erkannt. Provenienz-Verknüpfung unklar."

    evidence_count = len(pg_findings) + sum(
        f.evidence.get("no_match_count", 0) for f in gnd_findings
    )

    actions = []
    if gnd_findings and (gnd_coverage is None or gnd_coverage < 0.7):
        actions.append("GND-Normdaten ergänzen (Autorität, Herkunft belegen)")
    if pg_findings:
        actions.append("Fehlende Herkunftsnachweise durch Quellenangaben ergänzen")
    if geo_findings:
        actions.append("Geografische Normdaten (Geonames) für Ortsbezüge anreichern")
    if not (gnd_findings or pg_findings or geo_findings):
        actions.append("Normdaten-Verlinkung (GND, Wikidata) prüfen und ergänzen")

    return QualityMeasureSummary(
        measure=QualityMeasureKey.PROVENANCE,
        score=score,
        status=_status_from_score(score),
        summary=summary,
        mapped_finding_categories=cats,
        evidence_count=evidence_count,
        recommended_actions=actions,
    )


def _compute_fitness_for_use(
    report: AnalysisReport,
    completeness_score: int | None,
    uniqueness_score: int | None,
    structural_score: int | None,
) -> QualityMeasureSummary:
    """Composite measure: average of completeness, uniqueness, structural validity."""
    cats = ["missing_values", "duplicate_records", "encoding_issues", "format_inconsistency", "schema_mismatch"]
    available = [s for s in [completeness_score, uniqueness_score, structural_score] if s is not None]

    if not available:
        return _no_data(QualityMeasureKey.FITNESS_FOR_USE, cats)

    score = round(sum(available) / len(available))

    if score >= 80:
        summary = f"Datensatz gut für Weiterverarbeitung geeignet (Score: {score}/100)."
    elif score >= 50:
        summary = f"Datensatz bedingt geeignet, Nacharbeit empfohlen (Score: {score}/100)."
    else:
        summary = f"Datensatz nicht publikationsreif, wesentliche Mängel (Score: {score}/100)."

    actions = []
    if completeness_score is not None and completeness_score < 70:
        actions.append("Vollständigkeit verbessern (fehlende Pflichtfelder ergänzen)")
    if uniqueness_score is not None and uniqueness_score < 80:
        actions.append("Duplikate bereinigen")
    if structural_score is not None and structural_score < 70:
        actions.append("Strukturelle Probleme beheben (Encoding, Format)")

    return QualityMeasureSummary(
        measure=QualityMeasureKey.FITNESS_FOR_USE,
        score=score,
        status=_status_from_score(score),
        summary=summary,
        mapped_finding_categories=cats,
        evidence_count=0,
        recommended_actions=actions,
    )


def _compute_risk_severity(report: AnalysisReport) -> QualityMeasureSummary:
    cats = ["all"]
    by_sev = report.findings_by_severity
    critical_findings = by_sev[Severity.CRITICAL]
    warning_findings = by_sev[Severity.WARNING]
    total_findings = len(report.findings)

    if total_findings == 0:
        return QualityMeasureSummary(
            measure=QualityMeasureKey.RISK_SEVERITY,
            score=100,
            status=QualityStatus.GOOD,
            summary="Keine Findings vorhanden. Risikoeinschätzung: sehr gering.",
            mapped_finding_categories=cats,
            evidence_count=0,
        )

    critical_ratio = len(critical_findings) / total_findings
    warning_ratio = len(warning_findings) / total_findings
    score = max(0, round(100 - critical_ratio * 80 - warning_ratio * 30))

    if not critical_findings:
        summary = (
            f"Keine kritischen Befunde. "
            f"{len(warning_findings)} Warnungen, "
            f"{total_findings - len(critical_findings) - len(warning_findings)} Hinweise."
        )
    else:
        summary = f"{len(critical_findings)} kritische Befunde erfordern sofortige Aufmerksamkeit."

    top_examples = [
        {
            "category": f.category.value,
            "message": f.message,
            "severity": f.severity.value,
            "scope": f.scope,
        }
        for f in critical_findings[:3]
    ]

    actions = []
    if critical_findings:
        actions.append("Kritische Findings vor Export oder Publikation beheben")
        if any(f.category == FindingCategory.DUPLICATE_RECORDS for f in critical_findings):
            actions.append("Duplicate-Record-Problem hat höchste Priorität")
    if warning_findings:
        actions.append("Warnungen in Arbeitspaket-Planung berücksichtigen")

    return QualityMeasureSummary(
        measure=QualityMeasureKey.RISK_SEVERITY,
        score=score,
        status=_status_from_score(score),
        summary=summary,
        mapped_finding_categories=cats,
        evidence_count=len(critical_findings) + len(warning_findings),
        top_examples=top_examples,
        recommended_actions=actions,
    )


def _compute_actionability(report: AnalysisReport) -> QualityMeasureSummary:
    cats = ["remediation_candidate"]
    all_findings = report.findings

    if not all_findings:
        return QualityMeasureSummary(
            measure=QualityMeasureKey.ACTIONABILITY,
            score=100,
            status=QualityStatus.GOOD,
            summary="Keine Findings — keine Aktionen erforderlich.",
            mapped_finding_categories=cats,
            evidence_count=0,
        )

    rc_findings = report.findings_by_category.get(FindingCategory.REMEDIATION_CANDIDATE, [])
    findings_with_suggestions = [f for f in all_findings if f.suggestion]
    suggestion_rate = len(findings_with_suggestions) / len(all_findings)
    score = round(suggestion_rate * 100)

    if score >= 80:
        summary = f"{len(findings_with_suggestions)}/{len(all_findings)} Findings haben Handlungsempfehlungen."
    else:
        summary = (
            f"Nur {len(findings_with_suggestions)}/{len(all_findings)} Findings haben "
            f"konkrete Handlungsempfehlungen. Manuelle Priorisierung nötig."
        )

    top_examples = [
        {
            "category": f.category.value,
            "severity": f.severity.value,
            "suggestion": f.suggestion,
        }
        for f in findings_with_suggestions[:3]
    ]

    actions = []
    if score < 60:
        actions.append("Weitere Handlungsempfehlungen zu offenen Findings erarbeiten")
    if rc_findings:
        actions.append(f"{len(rc_findings)} Findings als automatisch behebbar markiert")
    actions.append("Findings nach Priorität in Arbeitspakete überführen")

    return QualityMeasureSummary(
        measure=QualityMeasureKey.ACTIONABILITY,
        score=score,
        status=_status_from_score(score),
        summary=summary,
        mapped_finding_categories=cats,
        evidence_count=len(findings_with_suggestions),
        top_examples=top_examples,
        recommended_actions=actions,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute_quality_measures(report: AnalysisReport) -> QualityMeasureReport:
    """Aggregate an AnalysisReport's findings into the 12 core quality measures."""
    completeness = _compute_completeness(report)
    uniqueness = _compute_uniqueness(report)
    structural = _compute_structural_validity(report)

    measures = [
        completeness,
        uniqueness,
        structural,
        _compute_consistency(report),
        _compute_semantic_correctness(report),
        _compute_normalization(report),
        _compute_clarity(report),
        _compute_cross_field_coherence(report),
        _compute_provenance(report),
        _compute_fitness_for_use(report, completeness.score, uniqueness.score, structural.score),
        _compute_risk_severity(report),
        _compute_actionability(report),
    ]

    return QualityMeasureReport(measures=measures)
