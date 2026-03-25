"""
Remediation — apply accepted RemediationSuggestions to a pandas DataFrame.

Entry point:
    apply_accepted_changes(df, suggestions, dataset_id, reviewer)
        →  (updated_df, list[AppliedChangeLog])

Only suggestions with status ACCEPTED are applied. Each accepted change
is recorded in an AppliedChangeLog entry so the operation is fully
traceable. The original DataFrame is not mutated; a copy is returned.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd

from kwb.core.models import (
    AppliedChangeLog,
    RemediationActionType,
    RemediationSuggestion,
    ReviewStatus,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_id() -> str:
    return str(uuid.uuid4())


def apply_accepted_changes(
    df: pd.DataFrame,
    suggestions: list[RemediationSuggestion],
    dataset_id: str,
    reviewer: str | None = None,
) -> tuple[pd.DataFrame, list[AppliedChangeLog]]:
    """Apply all ACCEPTED RemediationSuggestions to *df* (copy).

    Returns:
        (updated DataFrame, list of AppliedChangeLog entries)
    """
    result = df.copy()
    changelog: list[AppliedChangeLog] = []
    now = _now_iso()

    for sug in suggestions:
        if sug.status != ReviewStatus.ACCEPTED:
            continue
        log = _apply_suggestion(result, sug, dataset_id, reviewer, now)
        if log is not None:
            changelog.append(log)

    return result, changelog


def _apply_suggestion(
    df: pd.DataFrame,
    sug: RemediationSuggestion,
    dataset_id: str,
    reviewer: str | None,
    now: str,
) -> AppliedChangeLog | None:
    """Apply a single suggestion in-place on *df*. Returns a log entry or None."""

    action = sug.action_type

    if action == RemediationActionType.APPLY_SUGGESTED_VALUE:
        return _apply_suggested_value(df, sug, dataset_id, reviewer, now)

    if action == RemediationActionType.MOVE_VALUE_TO_FIELD:
        return _move_value_to_field(df, sug, dataset_id, reviewer, now)

    if action == RemediationActionType.NORMALIZE_LABEL:
        return _normalize_label(df, sug, dataset_id, reviewer, now)

    if action == RemediationActionType.SPLIT_MULTI_VALUE:
        # Split is advisory only — not directly applicable to a single cell
        # without knowing the delimiter and target columns.
        return None

    if action == RemediationActionType.FLAG_FOR_AUTHORITY_LOOKUP:
        # Flagging doesn't change values; we just log the intent.
        return AppliedChangeLog(
            change_id=_make_id(),
            dataset_id=dataset_id,
            record_id=sug.item_id or "",
            column=sug.target_field or "",
            original_value=sug.original_value,
            new_value=sug.original_value,  # unchanged
            action_type=action,
            applied_at=now,
            reviewer=reviewer,
            suggestion_id=sug.suggestion_id,
            item_id=sug.item_id,
            package_id=sug.package_id,
            is_ai_based=sug.is_ai_based,
            note="Flagged for authority lookup — value unchanged",
        )

    if action == RemediationActionType.LEAVE_UNCHANGED_MARK_UNCERTAIN:
        return AppliedChangeLog(
            change_id=_make_id(),
            dataset_id=dataset_id,
            record_id=sug.item_id or "",
            column=sug.target_field or "",
            original_value=sug.original_value,
            new_value=sug.original_value,
            action_type=action,
            applied_at=now,
            reviewer=reviewer,
            suggestion_id=sug.suggestion_id,
            item_id=sug.item_id,
            package_id=sug.package_id,
            is_ai_based=sug.is_ai_based,
            note="Marked as uncertain — value unchanged",
        )

    return None


def _find_rows(df: pd.DataFrame, record_id_hint: str | None) -> pd.Index:
    """Return the index of rows matching the record_id hint."""
    if record_id_hint is None:
        return pd.Index([])
    # Try common id columns
    for id_col in ("record_id", "id", "identifier", "ID"):
        if id_col in df.columns:
            mask = df[id_col].astype(str) == str(record_id_hint)
            if mask.any():
                return df.index[mask]
    return pd.Index([])


def _apply_suggested_value(
    df: pd.DataFrame,
    sug: RemediationSuggestion,
    dataset_id: str,
    reviewer: str | None,
    now: str,
) -> AppliedChangeLog | None:
    col = sug.target_field
    if not col or col not in df.columns:
        return None
    rows = _find_rows(df, sug.item_id)
    if rows.empty:
        # Fall back: apply to all cells matching original_value
        if sug.original_value is not None:
            mask = df[col].astype(str) == str(sug.original_value)
            rows = df.index[mask]
    if rows.empty:
        return None
    original = df.at[rows[0], col]
    df.loc[rows, col] = sug.suggested_value
    return AppliedChangeLog(
        change_id=_make_id(),
        dataset_id=dataset_id,
        record_id=str(sug.item_id or rows[0]),
        column=col,
        original_value=str(original) if original is not None else None,
        new_value=sug.suggested_value,
        action_type=sug.action_type,
        applied_at=now,
        reviewer=reviewer,
        suggestion_id=sug.suggestion_id,
        item_id=sug.item_id,
        package_id=sug.package_id,
        is_ai_based=sug.is_ai_based,
    )


def _move_value_to_field(
    df: pd.DataFrame,
    sug: RemediationSuggestion,
    dataset_id: str,
    reviewer: str | None,
    now: str,
) -> AppliedChangeLog | None:
    """Move original_value from one column (item_id encodes source col) to target_field."""
    target_col = sug.target_field
    if not target_col:
        return None
    if target_col not in df.columns:
        df[target_col] = ""
    rows = _find_rows(df, sug.item_id)
    if rows.empty:
        return None
    original = df.at[rows[0], target_col] if target_col in df.columns else None
    df.loc[rows, target_col] = sug.suggested_value or sug.original_value
    return AppliedChangeLog(
        change_id=_make_id(),
        dataset_id=dataset_id,
        record_id=str(sug.item_id or rows[0]),
        column=target_col,
        original_value=str(original) if original is not None else None,
        new_value=sug.suggested_value or sug.original_value,
        action_type=sug.action_type,
        applied_at=now,
        reviewer=reviewer,
        suggestion_id=sug.suggestion_id,
        item_id=sug.item_id,
        package_id=sug.package_id,
        is_ai_based=sug.is_ai_based,
    )


def _normalize_label(
    df: pd.DataFrame,
    sug: RemediationSuggestion,
    dataset_id: str,
    reviewer: str | None,
    now: str,
) -> AppliedChangeLog | None:
    col = sug.target_field
    if not col or col not in df.columns:
        return None
    if sug.original_value is None or sug.suggested_value is None:
        return None
    mask = df[col].astype(str) == str(sug.original_value)
    if not mask.any():
        return None
    df.loc[mask, col] = sug.suggested_value
    count = int(mask.sum())
    return AppliedChangeLog(
        change_id=_make_id(),
        dataset_id=dataset_id,
        record_id="batch",
        column=col,
        original_value=sug.original_value,
        new_value=sug.suggested_value,
        action_type=sug.action_type,
        applied_at=now,
        reviewer=reviewer,
        suggestion_id=sug.suggestion_id,
        item_id=sug.item_id,
        package_id=sug.package_id,
        is_ai_based=sug.is_ai_based,
        note=f"Batch normalization: {count} cells updated",
    )
