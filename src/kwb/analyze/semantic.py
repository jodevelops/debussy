"""
Semantic analysis — AI-powered metadata classification and image description.

Uses the AI provider abstraction, so it works with GPUStack, Ollama, or Mock.
Each function produces Findings just like structural.py does.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

from kwb.core.models import (
    DatasetProfile,
    Finding,
    FindingCategory,
    Severity,
)
from kwb.ai.provider import AIMessage, AIProvider
from kwb.ai.prompts import (
    prompt_classify_subject,
    prompt_describe_image,
    prompt_ocr_analysis,
    CLASSIFICATION_CATEGORIES,
)
from kwb.ai.batch import BatchReport, BatchResult, process_batch, _try_parse_json
from kwb.ingest.image_loader import ImageProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subject classification
# ---------------------------------------------------------------------------

def classify_subjects(
    df: pd.DataFrame,
    profile: DatasetProfile,
    provider: AIProvider,
    subject_column: str = "subject_extract_original",
    sample_size: int | None = None,
    model: str | None = None,
) -> tuple[list[Finding], BatchReport]:
    """
    Classify subject strings using an AI provider.

    Args:
        df: The dataset.
        profile: Its profile.
        provider: AI provider to use.
        subject_column: Column containing subject strings.
        sample_size: If set, only classify a random sample (for testing).
        model: Override model name.

    Returns:
        (findings, batch_report) — quality findings + raw AI results.
    """
    findings: list[Finding] = []

    if subject_column not in df.columns:
        findings.append(Finding(
            category=FindingCategory.SCHEMA_MISMATCH,
            severity=Severity.WARNING,
            message=f"Subject column '{subject_column}' not found in dataset",
        ))
        return findings, BatchReport()

    # Prepare items: only rows with non-empty subjects
    mask = df[subject_column].replace("", pd.NA).notna()
    working_df = df[mask].copy()

    if sample_size and sample_size < len(working_df):
        working_df = working_df.sample(n=sample_size, random_state=42)

    items = []
    for _, row in working_df.iterrows():
        record_id = row.get(profile.id_column, "") if profile.id_column else ""
        items.append({
            "record_id": str(record_id),
            "subject_text": str(row[subject_column]),
        })

    if not items:
        findings.append(Finding(
            category=FindingCategory.MISSING_VALUES,
            severity=Severity.INFO,
            message=f"No non-empty values in '{subject_column}' to classify",
            column=subject_column,
        ))
        return findings, BatchReport()

    def _make_prompt(item: dict[str, Any]) -> list[AIMessage]:
        return prompt_classify_subject(
            subject_text=item["subject_text"],
            context=f"Record: {item['record_id']}",
        )

    def _on_progress(current: int, total: int, result: BatchResult) -> None:
        if current % 50 == 0 or current == total:
            status = "OK" if result.success else "FAIL"
            logger.info(f"Classification: {current}/{total} [{status}]")

    batch_report = process_batch(
        provider=provider,
        items=items,
        prompt_fn=_make_prompt,
        model=model,
        on_progress=_on_progress,
    )

    # Analyze results
    misclassifications = []
    unclassified_terms = []

    for result in batch_report.results:
        if result.parsed:
            for term in result.parsed.get("unclassified", []):
                unclassified_terms.append({"term": term, "record_id": result.record_id})
            for cls in result.parsed.get("classifications", []):
                if cls.get("confidence", 0) < 0.5:
                    misclassifications.append({
                        "term": cls.get("term"),
                        "category": cls.get("category"),
                        "confidence": cls.get("confidence"),
                        "record_id": result.record_id,
                    })

    if unclassified_terms:
        findings.append(Finding(
            category=FindingCategory.CLASSIFICATION_INCONSISTENCY,
            severity=Severity.WARNING,
            message=f"{len(unclassified_terms)} terms could not be classified into any category",
            column=subject_column,
            record_ids=[t["record_id"] for t in unclassified_terms[:10]],
            evidence={"unclassified": unclassified_terms[:20]},
            suggestion="Review these terms — they may need new categories or manual assignment",
        ))

    if misclassifications:
        findings.append(Finding(
            category=FindingCategory.CLASSIFICATION_INCONSISTENCY,
            severity=Severity.INFO,
            message=f"{len(misclassifications)} classifications have low confidence (<50%)",
            column=subject_column,
            evidence={"low_confidence": misclassifications[:20]},
            suggestion="These may indicate ambiguous or unusual terms worth reviewing",
        ))

    # Summary finding
    findings.append(Finding(
        category=FindingCategory.CLASSIFICATION_INCONSISTENCY,
        severity=Severity.INFO,
        message=(
            f"Semantic classification complete: {batch_report.succeeded}/{batch_report.total} "
            f"records processed ({batch_report.success_rate:.0%} success rate, "
            f"avg {batch_report.avg_duration:.2f}s per record)"
        ),
        column=subject_column,
        evidence={
            "total": batch_report.total,
            "succeeded": batch_report.succeeded,
            "failed": batch_report.failed,
            "avg_duration_seconds": round(batch_report.avg_duration, 3),
        },
    ))

    return findings, batch_report


# ---------------------------------------------------------------------------
# Image description
# ---------------------------------------------------------------------------

def describe_images(
    images: list[ImageProfile],
    provider: AIProvider,
    model: str | None = None,
) -> tuple[list[Finding], BatchReport]:
    """
    Generate structured descriptions for a list of images.

    Returns:
        (findings, batch_report)
    """
    findings: list[Finding] = []

    if not images:
        return findings, BatchReport()

    # Filter to images with base64 data
    processable = [img for img in images if img.base64_data]
    skipped = len(images) - len(processable)

    if skipped > 0:
        findings.append(Finding(
            category=FindingCategory.MISSING_VALUES,
            severity=Severity.INFO,
            message=f"{skipped} images skipped (no base64 data loaded)",
        ))

    items = [
        {"record_id": img.filename, "base64": img.base64_data, "mime": img.mime_type}
        for img in processable
    ]

    def _make_prompt(item: dict[str, Any]) -> list[AIMessage]:
        msgs = prompt_describe_image(additional_context=item["record_id"])
        # Replace the last user message with a multimodal one
        text_content = msgs[-1].content if isinstance(msgs[-1].content, str) else ""
        vision_msg = AIMessage.user_with_image(
            text=text_content,
            image_base64=item["base64"],
            mime_type=item["mime"],
        )
        return [msgs[0], vision_msg]

    batch_report = process_batch(
        provider=provider,
        items=items,
        prompt_fn=_make_prompt,
        model=model,
    )

    findings.append(Finding(
        category=FindingCategory.NORM_DATA_CANDIDATE,
        severity=Severity.INFO,
        message=(
            f"Image description complete: {batch_report.succeeded}/{batch_report.total} "
            f"images processed ({batch_report.success_rate:.0%} success)"
        ),
        evidence={
            "total": batch_report.total,
            "succeeded": batch_report.succeeded,
            "failed": batch_report.failed,
        },
    ))

    return findings, batch_report
