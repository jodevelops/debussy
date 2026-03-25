"""
ReviewQueue — build, filter and update curatorial review items.

Entry point:
    ReviewQueue.from_quality_report(report)  →  ReviewQueue

The queue is built from a QualityAnalysisReport (Phase 1 + 2).  Each
CellFinding, RecordQualityReport (if review_required) and IssueCluster
becomes one or more ReviewItems.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from kwb.core.models import (
    FindingCategory,
    QualityAnalysisReport,
    ReviewDecision,
    ReviewItem,
    ReviewStatus,
    Severity,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_id() -> str:
    return str(uuid.uuid4())


class ReviewQueue:
    """In-memory queue of ReviewItems derived from a QualityAnalysisReport."""

    def __init__(self) -> None:
        self._items: dict[str, ReviewItem] = {}
        self._decisions: list[ReviewDecision] = []

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_quality_report(
        cls,
        report: QualityAnalysisReport,
        source: str = "",
        is_ai_based: bool = False,
    ) -> "ReviewQueue":
        """Build a ReviewQueue from a QualityAnalysisReport.

        Creates ReviewItems from:
        - cell_findings (one item per cell finding)
        - record_reports where review_required is True (one item per record)
        - issue_clusters (one item per cluster, at dataset level)
        """
        queue = cls()

        # Cell-level findings
        for cf in report.cell_findings:
            queue.add_item(
                ReviewItem(
                    item_id=_make_id(),
                    source=source or (cf.evidence.get("source", "") if cf.evidence else ""),
                    record_id=cf.record_id,
                    column=cf.column,
                    original_value=cf.value,
                    category=cf.category,
                    severity=cf.severity,
                    confidence=cf.confidence,
                    message=cf.message,
                    reasoning=cf.reasoning,
                    suggested_action=cf.suggested_action,
                    is_ai_based=is_ai_based,
                )
            )

        # Record-level findings that require review
        for rr in report.record_reports:
            if not rr.review_required:
                continue
            queue.add_item(
                ReviewItem(
                    item_id=_make_id(),
                    source=source or rr.source,
                    record_id=rr.record_id,
                    column=None,
                    original_value=None,
                    category=FindingCategory.CROSS_FIELD_CONFLICT,
                    severity=rr.severity or Severity.WARNING,
                    confidence=rr.confidence,
                    message="; ".join(rr.issues) if rr.issues else rr.reasoning,
                    reasoning=rr.reasoning,
                    suggested_action=None,
                    is_ai_based=is_ai_based,
                )
            )

        # Issue-cluster level (dataset/column scope)
        for cluster in report.issue_clusters:
            if cluster.severity == Severity.INFO:
                continue  # skip info-only clusters from queue
            queue.add_item(
                ReviewItem(
                    item_id=_make_id(),
                    source=source,
                    record_id=None,
                    column=cluster.affected_columns[0] if cluster.affected_columns else None,
                    original_value=None,
                    category=cluster.category,
                    severity=cluster.severity,
                    confidence=None,
                    message=cluster.label,
                    reasoning=f"Cluster betrifft {cluster.affected_records_count} Datensätze "
                    f"in Spalten: {', '.join(cluster.affected_columns)}",
                    suggested_action=cluster.suggested_action,
                    source_issue_ids=[cluster.cluster_id],
                    is_ai_based=False,
                )
            )

        return queue

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_item(self, item: ReviewItem) -> None:
        self._items[item.item_id] = item

    def get_item(self, item_id: str) -> ReviewItem | None:
        return self._items.get(item_id)

    def all_items(self) -> list[ReviewItem]:
        return list(self._items.values())

    def update_status(
        self,
        item_id: str,
        new_status: ReviewStatus,
        reviewer: str | None = None,
        note: str | None = None,
    ) -> ReviewItem | None:
        """Update the status of a ReviewItem and record the decision."""
        item = self._items.get(item_id)
        if item is None:
            return None
        item.status = new_status
        item.reviewer = reviewer
        item.reviewed_at = _now_iso()
        decision = ReviewDecision(
            item_id=item_id,
            decision=new_status,
            reviewed_at=item.reviewed_at,
            reviewer=reviewer,
            note=note,
        )
        self._decisions.append(decision)
        return item

    def decisions(self) -> list[ReviewDecision]:
        return list(self._decisions)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def filter(
        self,
        *,
        severity: str | None = None,
        column: str | None = None,
        category: str | None = None,
        status: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
        source: str | None = None,
        is_ai_based: bool | None = None,
    ) -> list[ReviewItem]:
        """Return items matching all provided filters."""
        items = list(self._items.values())
        if severity is not None:
            items = [i for i in items if i.severity.value == severity]
        if column is not None:
            items = [i for i in items if i.column == column]
        if category is not None:
            items = [i for i in items if i.category.value == category]
        if status is not None:
            items = [i for i in items if i.status.value == status]
        if min_confidence is not None:
            items = [i for i in items if i.confidence is not None and i.confidence >= min_confidence]
        if max_confidence is not None:
            items = [i for i in items if i.confidence is not None and i.confidence <= max_confidence]
        if source is not None:
            items = [i for i in items if i.source == source]
        if is_ai_based is not None:
            items = [i for i in items if i.is_ai_based == is_ai_based]
        return items

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        items = list(self._items.values())
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_category: dict[str, int] = {}
        for item in items:
            by_status[item.status.value] = by_status.get(item.status.value, 0) + 1
            by_severity[item.severity.value] = by_severity.get(item.severity.value, 0) + 1
            by_category[item.category.value] = by_category.get(item.category.value, 0) + 1
        return {
            "total": len(items),
            "by_status": by_status,
            "by_severity": by_severity,
            "by_category": by_category,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [i.to_dict() for i in self._items.values()],
            "decisions": [d.to_dict() for d in self._decisions],
            "summary": self.summary(),
        }
