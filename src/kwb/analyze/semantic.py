"""Semantic analysis — AI-powered metadata classification and image description."""
from __future__ import annotations
import logging
from typing import Any
import pandas as pd
from kwb.core.models import DatasetProfile, Finding, FindingCategory, Severity
from kwb.ai.provider import AIMessage, AIProvider
from kwb.ai.prompts import prompt_classify_subject, prompt_describe_image
from kwb.ai.batch import BatchReport, BatchResult, process_batch, _try_parse_json
from kwb.ingest.image_loader import ImageProfile

logger = logging.getLogger(__name__)


def classify_subjects(df, profile, provider, subject_column="subject_extract_original",
                      sample_size=None, model=None):
    findings = []
    if subject_column not in df.columns:
        findings.append(Finding(category=FindingCategory.SCHEMA_MISMATCH, severity=Severity.WARNING,
            message=f"Subject column '{subject_column}' not found in dataset"))
        return findings, BatchReport()
    mask = df[subject_column].replace("", pd.NA).notna()
    working_df = df[mask].copy()
    if sample_size and sample_size < len(working_df):
        working_df = working_df.sample(n=sample_size, random_state=42)
    items = [{"record_id": str(row.get(profile.id_column, "") if profile.id_column else ""),
              "subject_text": str(row[subject_column])} for _, row in working_df.iterrows()]
    if not items:
        findings.append(Finding(category=FindingCategory.MISSING_VALUES, severity=Severity.INFO,
            message=f"No non-empty values in '{subject_column}'", column=subject_column))
        return findings, BatchReport()

    def _make_prompt(item):
        return prompt_classify_subject(item["subject_text"], context=f"Record: {item['record_id']}")

    batch_report = process_batch(provider, items, _make_prompt, model=model)
    unclassified_terms, misclassifications = [], []
    for result in batch_report.results:
        if result.parsed:
            for t in result.parsed.get("unclassified", []):
                unclassified_terms.append({"term": t, "record_id": result.record_id})
            for cls in result.parsed.get("classifications", []):
                if cls.get("confidence", 0) < 0.5:
                    misclassifications.append({"term": cls.get("term"), "record_id": result.record_id})
    if unclassified_terms:
        findings.append(Finding(category=FindingCategory.CLASSIFICATION_INCONSISTENCY, severity=Severity.WARNING,
            message=f"{len(unclassified_terms)} terms could not be classified", column=subject_column,
            record_ids=[t["record_id"] for t in unclassified_terms[:10]]))
    findings.append(Finding(category=FindingCategory.CLASSIFICATION_INCONSISTENCY, severity=Severity.INFO,
        message=f"Semantic classification: {batch_report.succeeded}/{batch_report.total} records ({batch_report.success_rate:.0%})",
        column=subject_column, evidence={"total": batch_report.total, "succeeded": batch_report.succeeded}))
    return findings, batch_report


def describe_images(images, provider, model=None):
    findings, batch = [], BatchReport()
    if not images: return findings, batch
    processable = [img for img in images if img.base64_data]
    items = [{"record_id": img.filename, "base64": img.base64_data, "mime": img.mime_type} for img in processable]

    def _make_prompt(item):
        msgs = prompt_describe_image(additional_context=item["record_id"])
        text_content = msgs[-1].content if isinstance(msgs[-1].content, str) else ""
        return [msgs[0], AIMessage.user_with_image(text_content, item["base64"], item["mime"])]

    batch = process_batch(provider, items, _make_prompt, model=model)
    findings.append(Finding(category=FindingCategory.NORM_DATA_CANDIDATE, severity=Severity.INFO,
        message=f"Image description: {batch.succeeded}/{batch.total} ({batch.success_rate:.0%})",
        evidence={"total": batch.total, "succeeded": batch.succeeded}))
    return findings, batch
