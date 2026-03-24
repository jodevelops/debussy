"""
Markdown report generator.

Takes an AnalysisReport and renders it as a structured, human-readable
Markdown document suitable for review, sharing, and archiving.
"""

from __future__ import annotations

from datetime import datetime, timezone

from kwb.core.models import (
    AnalysisReport,
    DatasetProfile,
    Finding,
    QualityMeasureReport,
    QualityStatus,
    Severity,
)


SEVERITY_ICONS = {
    Severity.CRITICAL: "🔴",
    Severity.WARNING: "🟡",
    Severity.INFO: "🔵",
}

STATUS_ICONS = {
    QualityStatus.GOOD: "✅",
    QualityStatus.NEEDS_REVIEW: "🟡",
    QualityStatus.CRITICAL: "🔴",
    QualityStatus.INSUFFICIENT_DATA: "⚪",
}

MEASURE_LABELS = {
    "completeness": "Vollständigkeit",
    "uniqueness": "Eindeutigkeit",
    "structural_validity": "Strukturelle Gültigkeit",
    "consistency": "Konsistenz",
    "semantic_correctness": "Semantische Korrektheit",
    "normalization": "Normalisierung",
    "clarity": "Klarheit / Interpretierbarkeit",
    "cross_field_coherence": "Feldzusammenhang",
    "provenance": "Provenienz / Rückverfolgbarkeit",
    "fitness_for_use": "Verwendbarkeit",
    "risk_severity": "Risiko / Schweregrad",
    "actionability": "Handlungsfähigkeit",
}


def _render_profile(profile: DatasetProfile) -> str:
    """Render a single dataset profile as a Markdown section."""
    lines = [
        f"### {profile.source_name}",
        "",
        "| Eigenschaft | Wert |",
        "|---|---|",
        f"| Datei | `{profile.source_path}` |",
        f"| Zeilen | {profile.row_count:,} |",
        f"| Spalten | {profile.column_count} |",
        f"| ID-Spalte | `{profile.id_column or '—'}` |",
        f"| Encoding | {profile.encoding_detected} |",
        f"| BOM | {'Ja' if profile.has_bom else 'Nein'} |",
        f"| Zeilenenden | {profile.line_ending} |",
        "",
    ]

    # Column fill rates as compact table
    lines.append("**Spalten-Übersicht:**")
    lines.append("")
    lines.append("| Spalte | Gefüllt | Unique | Beispiel |")
    lines.append("|---|---|---|---|")
    for col in profile.columns:
        fill_pct = f"{col.fill_rate:.0%}"
        example = col.sample_values[0][:50] if col.sample_values else "—"
        example = example.replace("|", "\\|")
        lines.append(f"| `{col.name}` | {fill_pct} | {col.unique_count:,} | {example} |")
    lines.append("")

    return "\n".join(lines)


def _render_finding(f: Finding) -> str:
    """Render a single finding as a Markdown block."""
    icon = SEVERITY_ICONS.get(f.severity, "⚪")
    lines = [f"- {icon} **{f.severity.value.upper()}** — {f.message}"]

    if f.column:
        lines.append(f"  - Spalte: `{f.column}`")
    if f.record_ids:
        ids_str = ", ".join(f"`{rid}`" for rid in f.record_ids[:5])
        suffix = f" … (+{len(f.record_ids) - 5} weitere)" if len(f.record_ids) > 5 else ""
        lines.append(f"  - Betroffene Records: {ids_str}{suffix}")
    if f.suggestion:
        lines.append(f"  - 💡 *{f.suggestion}*")

    return "\n".join(lines)


def _score_bar(score: int | None, width: int = 10) -> str:
    """Render a compact ASCII progress bar for a 0-100 score."""
    if score is None:
        return "—"
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled) + f" {score}/100"


def _render_quality_measures(qm_report: QualityMeasureReport) -> str:
    """Render the 12 core quality measures as a Markdown section."""
    lines = [
        "## 12 Kerndimensionen der Datenqualität",
        "",
        "Überblick über die harmonisierten Qualitätsmaßzahlen — abgeleitet aus den detaillierten Findings.",
        "",
        "| # | Maßzahl | Score | Status | Zusammenfassung |",
        "|---|---|---|---|---|",
    ]

    for i, m in enumerate(qm_report.measures, 1):
        label = MEASURE_LABELS.get(m.measure.value, m.measure.value)
        icon = STATUS_ICONS.get(m.status, "⚪")
        score_str = f"{m.score}/100" if m.score is not None else "—"
        summary_escaped = m.summary.replace("|", "\\|")
        lines.append(f"| {i} | **{label}** | {score_str} | {icon} {m.status.value} | {summary_escaped} |")

    lines.append("")

    # Detail blocks for measures that need attention
    attention = [m for m in qm_report.measures if m.status in (QualityStatus.CRITICAL, QualityStatus.NEEDS_REVIEW)]
    if attention:
        lines.append("### Maßzahlen mit Handlungsbedarf")
        lines.append("")
        for m in attention:
            label = MEASURE_LABELS.get(m.measure.value, m.measure.value)
            icon = STATUS_ICONS.get(m.status, "⚪")
            lines.append(f"#### {icon} {label}")
            lines.append("")
            lines.append(f"**Score:** {m.score}/100 — {m.summary}")
            lines.append("")
            if m.recommended_actions:
                lines.append("**Empfohlene Maßnahmen:**")
                lines.append("")
                for action in m.recommended_actions:
                    lines.append(f"- {action}")
                lines.append("")
            if m.top_examples:
                lines.append("**Beispiele:**")
                lines.append("")
                for ex in m.top_examples[:3]:
                    col = ex.get("column") or ex.get("category", "")
                    detail = ex.get("message") or ex.get("summary") or str(ex)
                    lines.append(f"- `{col}`: {detail}")
                lines.append("")

    return "\n".join(lines)


def render_report(report: AnalysisReport) -> str:
    """Render a complete AnalysisReport as Markdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    s = report.summary

    sections = []

    # Header
    sections.append("# Datenqualitätsbericht")
    sections.append("")
    sections.append(f"*Erstellt: {now}*")
    sections.append("")

    # Executive summary
    sections.append("## Zusammenfassung")
    sections.append("")
    sections.append(
        f"| | Anzahl |\n|---|---|\n"
        f"| Datensätze analysiert | {s.get('datasets_analyzed', 0)} |\n"
        f"| Records gesamt | {s.get('total_records', 0):,} |\n"
        f"| Spalten gesamt | {s.get('total_columns', 0)} |\n"
        f"| 🔴 Kritisch | {s.get('critical', 0)} |\n"
        f"| 🟡 Warnungen | {s.get('warnings', 0)} |\n"
        f"| 🔵 Hinweise | {s.get('info', 0)} |\n"
        f"| **Findings gesamt** | **{s.get('total_findings', 0)}** |"
    )
    sections.append("")

    # 12 core quality measures (rendered before detailed findings)
    if report.quality_measures:
        sections.append(_render_quality_measures(report.quality_measures))

    # Dataset profiles
    sections.append("## Datensatz-Profile")
    sections.append("")
    for profile in report.datasets:
        sections.append(_render_profile(profile))

    # Findings grouped by severity
    sections.append("## Findings")
    sections.append("")

    by_severity = report.findings_by_severity
    for severity in [Severity.CRITICAL, Severity.WARNING, Severity.INFO]:
        findings = by_severity[severity]
        if not findings:
            continue
        icon = SEVERITY_ICONS[severity]
        sections.append(f"### {icon} {severity.value.capitalize()} ({len(findings)})")
        sections.append("")
        for f in findings:
            sections.append(_render_finding(f))
            sections.append("")

    # Category index
    sections.append("## Findings nach Kategorie")
    sections.append("")
    by_cat = report.findings_by_category
    for cat, findings in sorted(by_cat.items(), key=lambda x: len(x[1]), reverse=True):
        sev_summary = ", ".join(
            f"{SEVERITY_ICONS[f.severity]}" for f in findings[:5]
        )
        sections.append(f"- **{cat.value}** — {len(findings)} Findings {sev_summary}")
    sections.append("")

    return "\n".join(sections)
