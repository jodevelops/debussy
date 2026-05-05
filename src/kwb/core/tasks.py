"""
Task generation from MDS validation gaps.

Derives actionable tasks from missing or incomplete MDS field mappings,
so users can work through them sequentially in the Debussy suite.
"""
from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from enum import Enum

from kwb.core.utils import utc_now_iso


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"


class TaskCategory(str, Enum):
    MAP_FIELD = "map_field"          # Field not yet mapped
    FILL_DATA = "fill_data"          # Field mapped but incomplete
    ENRICH = "enrich"                # Enrich with authority data
    REVIEW = "review"                # Review AI suggestions
    NORMALIZE = "normalize"          # Normalize dates/formats
    CUSTOM = "custom"


@dataclass
class CurationTask:
    """A single actionable task derived from data gaps."""
    task_id: str = ""
    title: str = ""
    description: str = ""
    category: TaskCategory = TaskCategory.CUSTOM
    status: TaskStatus = TaskStatus.OPEN
    priority: int = 0                 # 0=highest
    mds_field: str = ""               # MDS field name if applicable
    goobi_type: str = ""              # Goobi metadata type if applicable
    csv_column: str = ""              # CSV column if applicable
    fill_rate: float = 0.0            # Current fill rate
    record_count: int = 0             # Affected records
    suggestion: str = ""              # How to resolve
    created_at: str = ""
    completed_at: str = ""
    note: str = ""

    def __post_init__(self):
        if not self.task_id:
            self.task_id = str(_uuid.uuid4())[:8]
        if not self.created_at:
            self.created_at = utc_now_iso()

    def complete(self, note: str = "") -> None:
        self.status = TaskStatus.DONE
        self.completed_at = utc_now_iso()
        if note:
            self.note = note

    def skip(self, note: str = "") -> None:
        self.status = TaskStatus.SKIPPED
        self.completed_at = utc_now_iso()
        if note:
            self.note = note

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "status": self.status.value,
            "priority": self.priority,
            "mds_field": self.mds_field,
            "goobi_type": self.goobi_type,
            "csv_column": self.csv_column,
            "fill_rate": round(self.fill_rate, 4),
            "record_count": self.record_count,
            "suggestion": self.suggestion,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "note": self.note,
        }

    @staticmethod
    def from_dict(d: dict) -> "CurationTask":
        return CurationTask(
            task_id=d.get("task_id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            category=TaskCategory(d.get("category", "custom")),
            status=TaskStatus(d.get("status", "open")),
            priority=int(d.get("priority", 0)),
            mds_field=d.get("mds_field", ""),
            goobi_type=d.get("goobi_type", ""),
            csv_column=d.get("csv_column", ""),
            fill_rate=float(d.get("fill_rate", 0)),
            record_count=int(d.get("record_count", 0)),
            suggestion=d.get("suggestion", ""),
            created_at=d.get("created_at", ""),
            completed_at=d.get("completed_at", ""),
            note=d.get("note", ""),
        )


def generate_tasks_from_mds(mds_report) -> list[CurationTask]:
    """
    Generate CurationTasks from an MdsValidationReport.

    Priority order:
      0 — Required fields not mapped
      1 — Required fields mapped but empty
      2 — Required fields mapped but < 50% filled
      3 — Recommended fields not mapped
      4 — Recommended fields mapped but < 50% filled
      5 — Optional fields with issues
    """
    tasks: list[CurationTask] = []

    for fr in mds_report.field_results:
        if not fr.mapped:
            # Field not mapped at all
            prio = 0 if fr.requirement == "required" else 3
            tasks.append(CurationTask(
                title=f"Feld zuordnen: {fr.mds_name}",
                description=(
                    f"Das MDS-Feld '{fr.mds_name}' ({fr.goobi_type}) ist keiner "
                    f"CSV-Spalte zugeordnet."
                ),
                category=TaskCategory.MAP_FIELD,
                priority=prio,
                mds_field=fr.mds_name,
                goobi_type=fr.goobi_type,
                record_count=fr.record_count,
                suggestion=(
                    f"Im Field-Mapping-Tab eine passende CSV-Spalte dem Typ "
                    f"'{fr.goobi_type}' zuordnen."
                ),
            ))
        elif fr.fill_rate == 0:
            # Mapped but completely empty
            prio = 1 if fr.requirement == "required" else 4
            tasks.append(CurationTask(
                title=f"Daten ergänzen: {fr.mds_name}",
                description=(
                    f"Das Feld '{fr.mds_name}' ist der Spalte '{fr.csv_column}' "
                    f"zugeordnet, enthält aber keine Werte."
                ),
                category=TaskCategory.FILL_DATA,
                priority=prio,
                mds_field=fr.mds_name,
                goobi_type=fr.goobi_type,
                csv_column=fr.csv_column,
                fill_rate=0.0,
                record_count=fr.record_count,
                suggestion="Spalte in der Quelldatei befüllen oder KI-Anreicherung nutzen.",
            ))
        elif fr.fill_rate < 0.5:
            # Mapped but partially filled
            prio = 2 if fr.requirement == "required" else 4
            empty = fr.record_count - fr.filled_count
            tasks.append(CurationTask(
                title=f"Lücken schließen: {fr.mds_name}",
                description=(
                    f"'{fr.mds_name}' ist nur zu {fr.fill_rate:.0%} befüllt "
                    f"({fr.filled_count}/{fr.record_count}). "
                    f"{empty} Einträge fehlen."
                ),
                category=TaskCategory.FILL_DATA,
                priority=prio,
                mds_field=fr.mds_name,
                goobi_type=fr.goobi_type,
                csv_column=fr.csv_column,
                fill_rate=fr.fill_rate,
                record_count=empty,
                suggestion=(
                    f"Fehlende Werte in Spalte '{fr.csv_column}' ergänzen. "
                    f"Ggf. NER oder KI-Beschreibungen nutzen."
                ),
            ))

    tasks.sort(key=lambda t: t.priority)
    return tasks
