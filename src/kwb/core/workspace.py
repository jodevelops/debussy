"""
Workspace — central state container for a curation session.

Holds:
- Field mapping (CSV column → Goobi metadata type)
- Normdaten-Wörterbuch (term → GND entry)
- Entity review status (pending / accepted / rejected)
- Session metadata

DESIGN NOTES:
- Pure Python dataclasses; no FastAPI, no DB dependency.
- All persistence is handled by callers (JSON serialize/deserialize).
- field_mapping is a list so order is preserved (UI table order).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Field Mapping
# ---------------------------------------------------------------------------

class GoobiMetadataType(str, Enum):
    """Common Goobi metadata types; not exhaustive — free-text also allowed."""
    CATALOG_ID       = "CatalogIDDigital"
    TITLE            = "TitleDocMain"
    DESCRIPTION      = "Description"
    PUBLICATION_YEAR = "PublicationYear"
    LANGUAGE         = "DocLanguage"
    COLLECTION       = "singleDigCollection"
    OBJECT_TYPE      = "DocStruct"
    MATERIAL         = "MaterialDescription"
    FORMAT           = "Format"
    TECHNIQUE        = "Technique"
    DIMENSIONS       = "Dimensions"
    INVENTORY_NR     = "InventoryNumber"
    CREATOR          = "Creator"
    PUBLISHER        = "Publisher"
    RIGHTS           = "Rights"
    SUBJECT          = "SubjectTopic"
    SUBJECT_GEO      = "SubjectGeographic"
    SUBJECT_PERSON   = "SubjectPerson"
    SUBJECT_CORP     = "SubjectCorporation"
    DATE_CREATED     = "DateCreated"
    DATE_ISSUED      = "DateIssued"
    GEO_LOCATION     = "PlaceOfPublication"
    CUSTOM           = "Custom"
    IGNORE           = "__ignore__"


@dataclass
class FieldMapping:
    """Maps one CSV column to one Goobi metadata type."""
    csv_column: str
    goobi_type: str               # GoobiMetadataType value or free-text
    label: str = ""               # Human-readable label for the GUI
    repeatable: bool = False      # True → one XML element per semicolon-value
    authority: str = ""           # "gnd" | "wikidata" | ""
    authority_uri: str = ""       # "http://d-nb.info/gnd/"
    enabled: bool = True          # False → column silently skipped
    note: str = ""

    @property
    def is_ignored(self) -> bool:
        return self.goobi_type == GoobiMetadataType.IGNORE.value or not self.enabled

    def to_dict(self) -> dict:
        return {
            "csv_column": self.csv_column,
            "goobi_type": self.goobi_type,
            "label": self.label,
            "repeatable": self.repeatable,
            "authority": self.authority,
            "authority_uri": self.authority_uri,
            "enabled": self.enabled,
            "note": self.note,
        }

    @staticmethod
    def from_dict(d: dict) -> "FieldMapping":
        return FieldMapping(**d)


# ---------------------------------------------------------------------------
# Normdaten-Wörterbuch
# ---------------------------------------------------------------------------

@dataclass
class DictionaryEntry:
    """A single normed term → GND authority mapping."""
    term: str                          # Original/preferred display term
    gnd_id: str = ""                   # e.g. "4074335-4"
    gnd_preferred: str = ""            # GND preferred name
    gnd_type: str = ""                 # "Geographic", "Person", "SubjectHeading", …
    gnd_uri: str = ""                  # full URI
    wikidata_id: str = ""              # "Q64"
    alternatives: list[str] = field(default_factory=list)
    confidence: float = 1.0
    source: str = "manual"            # "manual" | "api" | "llm"
    note: str = ""

    @property
    def has_authority(self) -> bool:
        return bool(self.gnd_id or self.wikidata_id)

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "gnd_id": self.gnd_id,
            "gnd_preferred": self.gnd_preferred,
            "gnd_type": self.gnd_type,
            "gnd_uri": self.gnd_uri,
            "wikidata_id": self.wikidata_id,
            "alternatives": self.alternatives,
            "confidence": self.confidence,
            "source": self.source,
            "note": self.note,
        }

    @staticmethod
    def from_dict(d: dict) -> "DictionaryEntry":
        e = DictionaryEntry(term=d["term"])
        for k, v in d.items():
            if hasattr(e, k):
                setattr(e, k, v)
        return e


# ---------------------------------------------------------------------------
# Entity Review Status
# ---------------------------------------------------------------------------

class ReviewStatus(str, Enum):
    PENDING  = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MERGED   = "merged"


@dataclass
class EntityReview:
    """Review decision for one named entity candidate."""
    text: str
    entity_type: str
    record_id: str
    status: ReviewStatus = ReviewStatus.PENDING
    gnd_id: str = ""
    gnd_preferred: str = ""
    reviewer_note: str = ""
    reviewed_at: str = ""

    def accept(self, gnd_id: str = "", gnd_preferred: str = "", note: str = "") -> None:
        self.status = ReviewStatus.ACCEPTED
        self.gnd_id = gnd_id
        self.gnd_preferred = gnd_preferred
        self.reviewer_note = note
        self.reviewed_at = datetime.utcnow().isoformat()

    def reject(self, note: str = "") -> None:
        self.status = ReviewStatus.REJECTED
        self.reviewer_note = note
        self.reviewed_at = datetime.utcnow().isoformat()

    @property
    def dedup_key(self) -> tuple[str, str]:
        return (self.text.lower(), self.entity_type)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "entity_type": self.entity_type,
            "record_id": self.record_id,
            "status": self.status.value,
            "gnd_id": self.gnd_id,
            "gnd_preferred": self.gnd_preferred,
            "reviewer_note": self.reviewer_note,
            "reviewed_at": self.reviewed_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "EntityReview":
        er = EntityReview(
            text=d["text"],
            entity_type=d["entity_type"],
            record_id=d.get("record_id", ""),
            status=ReviewStatus(d.get("status", "pending")),
        )
        er.gnd_id = d.get("gnd_id", "")
        er.gnd_preferred = d.get("gnd_preferred", "")
        er.reviewer_note = d.get("reviewer_note", "")
        er.reviewed_at = d.get("reviewed_at", "")
        return er


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

@dataclass
class Workspace:
    """
    Central state for one curation project.

    Typical lifecycle:
        ws = Workspace.create("GIUB Hauptsammlung")
        ws.set_field_mapping([FieldMapping(...), ...])
        ws.add_entities(entities)
        json_str = ws.to_json()
    """
    name: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    source_file: str = ""
    id_column: str = "record_id"

    # Field mapping: ordered list
    field_mapping: list[FieldMapping] = field(default_factory=list)

    # Normdaten-Wörterbuch: term → entry
    dictionary: dict[str, DictionaryEntry] = field(default_factory=dict)

    # Entity review queue
    entity_reviews: list[EntityReview] = field(default_factory=list)

    # Free-form session notes
    notes: str = ""

    # AI model selection (persisted so re-runs are reproducible)
    model_text: str = ""
    model_vision: str = ""

    # Arbitrary extra data (e.g. QA findings)
    extras: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(name: str, source_file: str = "") -> "Workspace":
        return Workspace(name=name, source_file=source_file)

    # ------------------------------------------------------------------
    # Field mapping helpers
    # ------------------------------------------------------------------

    def set_field_mapping(self, mappings: list[FieldMapping]) -> None:
        self.field_mapping = mappings
        self._touch()

    def get_mapping(self, csv_column: str) -> FieldMapping | None:
        for m in self.field_mapping:
            if m.csv_column == csv_column:
                return m
        return None

    def add_or_update_mapping(self, mapping: FieldMapping) -> None:
        for i, m in enumerate(self.field_mapping):
            if m.csv_column == mapping.csv_column:
                self.field_mapping[i] = mapping
                self._touch()
                return
        self.field_mapping.append(mapping)
        self._touch()

    def active_mappings(self) -> list[FieldMapping]:
        """Return only enabled, non-ignored mappings."""
        return [m for m in self.field_mapping if not m.is_ignored]

    # ------------------------------------------------------------------
    # Dictionary helpers
    # ------------------------------------------------------------------

    def add_entry(self, entry: DictionaryEntry) -> None:
        self.dictionary[entry.term.lower()] = entry
        self._touch()

    def lookup(self, term: str) -> DictionaryEntry | None:
        return self.dictionary.get(term.lower())

    def lookup_gnd(self, gnd_id: str) -> DictionaryEntry | None:
        for e in self.dictionary.values():
            if e.gnd_id == gnd_id:
                return e
        return None

    # ------------------------------------------------------------------
    # Entity review helpers
    # ------------------------------------------------------------------

    def add_entities(self, entities: list[dict]) -> int:
        """
        Add entity dicts (from NERResult.to_dict_list()) to the review queue.

        Skips exact duplicates (same text+type+record_id).
        Returns number of newly added reviews.
        """
        existing_keys = {
            (r.text.lower(), r.entity_type, r.record_id)
            for r in self.entity_reviews
        }
        added = 0
        for e in entities:
            key = (e["text"].lower(), e["type"], e.get("record_id", ""))
            if key not in existing_keys:
                self.entity_reviews.append(EntityReview(
                    text=e["text"],
                    entity_type=e["type"],
                    record_id=e.get("record_id", ""),
                    gnd_id=e.get("gnd_id") or "",
                    gnd_preferred=e.get("gnd_preferred") or "",
                ))
                existing_keys.add(key)
                added += 1
        self._touch()
        return added

    def reviews_by_status(self, status: ReviewStatus) -> list[EntityReview]:
        return [r for r in self.entity_reviews if r.status == status]

    def review_stats(self) -> dict[str, int]:
        stats: dict[str, int] = {s.value: 0 for s in ReviewStatus}
        for r in self.entity_reviews:
            stats[r.status.value] += 1
        stats["total"] = len(self.entity_reviews)
        return stats

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _touch(self) -> None:
        self.updated_at = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_file": self.source_file,
            "id_column": self.id_column,
            "field_mapping": [m.to_dict() for m in self.field_mapping],
            "dictionary": {k: v.to_dict() for k, v in self.dictionary.items()},
            "entity_reviews": [r.to_dict() for r in self.entity_reviews],
            "notes": self.notes,
            "model_text": self.model_text,
            "model_vision": self.model_vision,
            "extras": self.extras,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @staticmethod
    def from_dict(d: dict) -> "Workspace":
        ws = Workspace(
            name=d["name"],
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            source_file=d.get("source_file", ""),
            id_column=d.get("id_column", "record_id"),
        )
        ws.field_mapping = [FieldMapping.from_dict(m) for m in d.get("field_mapping", [])]
        ws.dictionary = {
            k: DictionaryEntry.from_dict(v)
            for k, v in d.get("dictionary", {}).items()
        }
        ws.entity_reviews = [
            EntityReview.from_dict(r) for r in d.get("entity_reviews", [])
        ]
        ws.notes = d.get("notes", "")
        ws.model_text = d.get("model_text", "")
        ws.model_vision = d.get("model_vision", "")
        ws.extras = d.get("extras", {})
        return ws

    @staticmethod
    def from_json(json_str: str) -> "Workspace":
        return Workspace.from_dict(json.loads(json_str))

    @staticmethod
    def load(path: str | Path) -> "Workspace":
        return Workspace.from_json(Path(path).read_text(encoding="utf-8"))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")
