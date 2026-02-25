"""
Structural analysis: rule-based quality checks on ingested data.

Each check is a standalone function that takes a DataFrame + DatasetProfile
and returns a list of Findings. This makes checks composable, testable,
and easy to extend.

No AI dependencies here — this is pure rule-based analysis.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from kwb.core.models import (
    AnalysisReport,
    DatasetProfile,
    Finding,
    FindingCategory,
    Severity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_affected_ids(
    df: pd.DataFrame, mask: pd.Series, id_column: str | None, limit: int = 10,
) -> list[str]:
    """Safely extract record IDs for affected rows."""
    if not id_column or id_column not in df.columns:
        return []
    try:
        return df.loc[mask, id_column].head(limit).tolist()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Individual checks — each returns a list of Findings
# ---------------------------------------------------------------------------


def check_missing_values(df: pd.DataFrame, profile: DatasetProfile) -> list[Finding]:
    """Identify columns with significant missing values."""
    findings = []
    df_analysis = df.replace("", pd.NA)

    for col_profile in profile.columns:
        col = col_profile.name
        missing_rate = 1.0 - col_profile.fill_rate

        if missing_rate == 0:
            continue

        if missing_rate >= 0.95:
            severity = Severity.INFO  # Nearly empty — might be intentional
            msg = f"Column '{col}' is nearly empty ({col_profile.fill_rate:.1%} filled)"
        elif missing_rate >= 0.5:
            severity = Severity.WARNING
            msg = f"Column '{col}' is half empty ({col_profile.fill_rate:.1%} filled, {col_profile.non_null_count}/{col_profile.total_count} values)"
        elif missing_rate >= 0.1:
            severity = Severity.WARNING
            msg = f"Column '{col}' has gaps ({col_profile.fill_rate:.1%} filled)"
        else:
            severity = Severity.INFO
            msg = f"Column '{col}' has minor gaps ({col_profile.fill_rate:.1%} filled)"

        # Collect affected record IDs (up to 10 as evidence)
        missing_mask = df_analysis[col].isna()
        affected_ids = _get_affected_ids(df, missing_mask, profile.id_column, 10)

        findings.append(Finding(
            category=FindingCategory.MISSING_VALUES,
            severity=severity,
            message=msg,
            column=col,
            record_ids=affected_ids,
            evidence={
                "fill_rate": col_profile.fill_rate,
                "missing_count": col_profile.total_count - col_profile.non_null_count,
            },
        ))

    return findings


def check_duplicate_records(df: pd.DataFrame, profile: DatasetProfile) -> list[Finding]:
    """Check for duplicate record IDs."""
    findings = []

    if not profile.id_column:
        findings.append(Finding(
            category=FindingCategory.SCHEMA_MISMATCH,
            severity=Severity.CRITICAL,
            message="No unique ID column detected — cannot check for duplicates",
        ))
        return findings

    id_col = profile.id_column
    dupes = df[df.duplicated(subset=[id_col], keep=False)]

    if len(dupes) > 0:
        dupe_ids = dupes[id_col].unique().tolist()[:20]
        findings.append(Finding(
            category=FindingCategory.DUPLICATE_RECORDS,
            severity=Severity.CRITICAL,
            message=f"Found {len(dupes)} rows with duplicate IDs ({len(dupes[id_col].unique())} unique IDs affected)",
            column=id_col,
            record_ids=dupe_ids,
            evidence={"duplicate_row_count": len(dupes)},
        ))

    return findings


def check_encoding_issues(df: pd.DataFrame, profile: DatasetProfile) -> list[Finding]:
    """Detect encoding artifacts in string values."""
    findings = []
    suspicious_patterns = {
        "\u00c3\u00a4": "UTF-8 decoded as Latin-1 (ae-umlaut)",
        "\u00c3\u00b6": "UTF-8 decoded as Latin-1 (oe-umlaut)",
        "\u00c3\u00bc": "UTF-8 decoded as Latin-1 (ue-umlaut)",
        "\u00c3\u00a9": "UTF-8 decoded as Latin-1 (e-accent)",
        "\u00c3\u00a0": "UTF-8 decoded as Latin-1 (a-grave)",
        "\u00e2\u0080\u0093": "UTF-8 decoded as Latin-1 (em-dash)",
        "\u00e2\u0080\u009c": "UTF-8 decoded as Latin-1 (left-quote)",
        "\u00c2": "Stray Latin-1 artifact",
    }

    for col in df.columns:
        col_str = df[col].astype(str)
        for pattern, description in suspicious_patterns.items():
            mask = col_str.str.contains(pattern, na=False)
            if mask.any():
                affected_ids = _get_affected_ids(df, mask, profile.id_column, 5)
                findings.append(Finding(
                    category=FindingCategory.ENCODING_ISSUES,
                    severity=Severity.WARNING,
                    message=f"Encoding artifact in '{col}': {description} ({mask.sum()} occurrences)",
                    column=col,
                    record_ids=affected_ids,
                    evidence={
                        "pattern": pattern,
                        "description": description,
                        "count": int(mask.sum()),
                    },
                ))

    # BOM check
    if profile.has_bom:
        findings.append(Finding(
            category=FindingCategory.ENCODING_ISSUES,
            severity=Severity.INFO,
            message="File has UTF-8 BOM (Byte Order Mark) — usually harmless but may cause issues with some tools",
            evidence={"bom": True},
        ))

    # Line ending check
    if profile.line_ending == "CRLF":
        findings.append(Finding(
            category=FindingCategory.ENCODING_ISSUES,
            severity=Severity.INFO,
            message="File uses Windows-style line endings (CRLF)",
            evidence={"line_ending": "CRLF"},
        ))

    return findings


def check_format_inconsistency(df: pd.DataFrame, profile: DatasetProfile) -> list[Finding]:
    """Detect inconsistent formatting within columns."""
    findings = []

    for col in df.columns:
        values = df[col].replace("", pd.NA).dropna().astype(str)
        if len(values) == 0:
            continue

        # Check: mixed delimiters in multi-value fields
        has_semicolons = values.str.contains(";", na=False)
        has_commas = values.str.contains(",", na=False)
        if has_semicolons.any() and has_commas.any():
            both_mask = has_semicolons & has_commas
            if both_mask.any():
                affected_ids = _get_affected_ids(df, both_mask, profile.id_column, 5)
                findings.append(Finding(
                    category=FindingCategory.FORMAT_INCONSISTENCY,
                    severity=Severity.WARNING,
                    message=f"Column '{col}' uses mixed delimiters (both ';' and ',') — {both_mask.sum()} rows affected",
                    column=col,
                    record_ids=affected_ids,
                    evidence={
                        "semicolon_rows": int(has_semicolons.sum()),
                        "comma_rows": int(has_commas.sum()),
                        "both_rows": int(both_mask.sum()),
                    },
                ))

        # Check: leading/trailing whitespace
        has_whitespace = values.str.match(r"^\s+.*|.*\s+$")
        if has_whitespace.any():
            affected_ids = _get_affected_ids(df, has_whitespace, profile.id_column, 5)
            findings.append(Finding(
                category=FindingCategory.FORMAT_INCONSISTENCY,
                severity=Severity.WARNING,
                message=f"Column '{col}' has leading/trailing whitespace in {has_whitespace.sum()} values",
                column=col,
                record_ids=affected_ids,
                evidence={"whitespace_count": int(has_whitespace.sum())},
            ))

    return findings


def check_term_variants(df: pd.DataFrame, profile: DatasetProfile) -> list[Finding]:
    """Detect likely term variants (case differences, minor spelling)."""
    findings = []

    for col in df.columns:
        values = df[col].replace("", pd.NA).dropna().astype(str)
        if len(values) == 0 or len(values.unique()) > 1000:
            continue  # Skip high-cardinality columns

        # Expand multi-value fields
        all_terms = []
        for v in values:
            for delimiter in [";", "|"]:
                if delimiter in v:
                    all_terms.extend([t.strip() for t in v.split(delimiter)])
                    break
            else:
                all_terms.append(v.strip())

        # Group by lowercased version
        lower_map: dict[str, list[str]] = {}
        for term in all_terms:
            if term:
                lower_map.setdefault(term.lower(), []).append(term)

        # Find variants
        variants_found = []
        for lower, originals in lower_map.items():
            unique_forms = list(set(originals))
            if len(unique_forms) > 1:
                variants_found.append({
                    "canonical": lower,
                    "forms": unique_forms,
                    "counts": {f: originals.count(f) for f in unique_forms},
                })

        if variants_found:
            findings.append(Finding(
                category=FindingCategory.TERM_VARIANTS,
                severity=Severity.WARNING,
                message=f"Column '{col}' has {len(variants_found)} term variant groups (e.g., case differences)",
                column=col,
                evidence={
                    "variant_count": len(variants_found),
                    "examples": variants_found[:5],
                },
                suggestion="Normalize terms to a consistent form before export",
            ))

    return findings


def check_cross_file_linkage(
    datasets: list[tuple[pd.DataFrame, DatasetProfile]],
) -> list[Finding]:
    """Check consistency across multiple files sharing a record_id."""
    findings = []
    if len(datasets) < 2:
        return findings

    id_sets: list[tuple[str, set[str]]] = []
    for df, profile in datasets:
        if profile.id_column:
            ids = set(df[profile.id_column].dropna().astype(str).tolist())
            id_sets.append((profile.source_name, ids))

    # Pairwise comparison
    for i, (name_a, ids_a) in enumerate(id_sets):
        for name_b, ids_b in id_sets[i + 1:]:
            shared = ids_a & ids_b
            only_a = ids_a - ids_b
            only_b = ids_b - ids_a

            if only_a:
                findings.append(Finding(
                    category=FindingCategory.ORPHAN_RECORDS,
                    severity=Severity.WARNING,
                    message=f"{len(only_a)} records in '{name_a}' have no match in '{name_b}'",
                    record_ids=sorted(only_a)[:10],
                    evidence={
                        "source": name_a,
                        "target": name_b,
                        "orphan_count": len(only_a),
                        "shared_count": len(shared),
                    },
                ))

            if only_b:
                findings.append(Finding(
                    category=FindingCategory.ORPHAN_RECORDS,
                    severity=Severity.WARNING,
                    message=f"{len(only_b)} records in '{name_b}' have no match in '{name_a}'",
                    record_ids=sorted(only_b)[:10],
                    evidence={
                        "source": name_b,
                        "target": name_a,
                        "orphan_count": len(only_b),
                        "shared_count": len(shared),
                    },
                ))

            if shared:
                findings.append(Finding(
                    category=FindingCategory.CROSS_FILE_MISMATCH,
                    severity=Severity.INFO,
                    message=f"'{name_a}' and '{name_b}' share {len(shared)} record IDs",
                    evidence={
                        "shared_count": len(shared),
                        "only_in_a": len(only_a),
                        "only_in_b": len(only_b),
                    },
                ))

    return findings


# ---------------------------------------------------------------------------
# GND-specific checks
# ---------------------------------------------------------------------------

def check_gnd_coverage(df: pd.DataFrame, profile: DatasetProfile) -> list[Finding]:
    """Analyze GND matching quality across named entity columns."""
    findings = []

    # Detect GND-related columns
    gnd_id_cols = [c for c in df.columns if "gnd_id" in c.lower()]
    gnd_konfidenz_cols = [c for c in df.columns if "gnd_konfidenz" in c.lower() or "konfidenz" in c.lower()]
    gnd_begruendung_cols = [c for c in df.columns if "gnd_begruendung" in c.lower() or "begruendung" in c.lower()]

    if not gnd_id_cols:
        return findings  # No GND data in this dataset

    # Count total NE slots vs filled GND IDs
    total_ne_slots = 0
    filled_gnd_ids = 0
    no_match_count = 0
    api_recommended = 0

    for col in gnd_id_cols:
        values = df[col].replace("", pd.NA)
        total_ne_slots += len(values)
        filled_gnd_ids += values.notna().sum()

    for col in gnd_begruendung_cols:
        values = df[col].astype(str)
        no_match_count += values.str.contains("Kein GND-Match", case=False, na=False).sum()
        api_recommended += values.str.contains("API-Abfrage empfohlen", case=False, na=False).sum()

    if total_ne_slots > 0:
        coverage = filled_gnd_ids / total_ne_slots
        findings.append(Finding(
            category=FindingCategory.GND_MATCH_MISSING,
            severity=Severity.WARNING if coverage < 0.5 else Severity.INFO,
            message=f"GND coverage: {filled_gnd_ids}/{total_ne_slots} entity slots have GND IDs ({coverage:.1%})",
            evidence={
                "total_ne_slots": total_ne_slots,
                "filled_gnd_ids": int(filled_gnd_ids),
                "coverage_rate": round(coverage, 4),
                "no_match_count": no_match_count,
                "api_recommended": api_recommended,
            },
            suggestion=f"{api_recommended} entries recommend API lookup — batch GND enrichment could fill these gaps",
        ))

    # Confidence distribution
    for col in gnd_konfidenz_cols:
        values = df[col].replace("", pd.NA).dropna().astype(str)
        if len(values) == 0:
            continue
        conf_counts = values.value_counts().to_dict()
        findings.append(Finding(
            category=FindingCategory.NORM_DATA_CANDIDATE,
            severity=Severity.INFO,
            message=f"GND confidence distribution in '{col}': {dict(list(conf_counts.items())[:5])}",
            column=col,
            evidence={"distribution": conf_counts},
        ))

    return findings


# ---------------------------------------------------------------------------
# Orchestrator — runs all checks
# ---------------------------------------------------------------------------

# Registry of all check functions for single datasets
SINGLE_DATASET_CHECKS = [
    check_missing_values,
    check_duplicate_records,
    check_encoding_issues,
    check_format_inconsistency,
    check_term_variants,
    check_gnd_coverage,
]


def analyze_datasets(
    datasets: list[tuple[pd.DataFrame, DatasetProfile]],
) -> AnalysisReport:
    """
    Run all registered checks across one or more datasets.
    Returns a complete AnalysisReport.
    """
    report = AnalysisReport()

    for df, profile in datasets:
        report.datasets.append(profile)

        for check_fn in SINGLE_DATASET_CHECKS:
            report.findings.extend(check_fn(df, profile))

    # Cross-file checks
    if len(datasets) > 1:
        report.findings.extend(check_cross_file_linkage(datasets))

    # Build summary
    by_sev = report.findings_by_severity
    report.summary = {
        "total_findings": len(report.findings),
        "critical": len(by_sev[Severity.CRITICAL]),
        "warnings": len(by_sev[Severity.WARNING]),
        "info": len(by_sev[Severity.INFO]),
        "datasets_analyzed": len(datasets),
        "total_records": sum(p.row_count for p in report.datasets),
        "total_columns": sum(p.column_count for p in report.datasets),
    }

    return report
