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


class ImageReviewStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass
class EntityReview:
    """Review decision for one named entity candidate."""
    text: str
    entity_type: str
    record_id: str = ""
    status: ReviewStatus = ReviewStatus.PENDING
    confidence: float = 0.0
    source: str = ""
    column: str = ""
    gnd_id: str = ""
    gnd_preferred: str = ""
    reviewer_note: str = ""
    editor_note: str = ""
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
            "confidence": self.confidence,
            "source": self.source,
            "gnd_id": self.gnd_id,
            "gnd_preferred": self.gnd_preferred,
            "reviewer_note": self.reviewer_note,
            "editor_note": self.editor_note,
            "reviewed_at": self.reviewed_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "EntityReview":
        er = EntityReview(
            text=d["text"],
            entity_type=d.get("entity_type", d.get("type", "")),
            record_id=d.get("record_id", ""),
            status=ReviewStatus(d.get("status", "pending")),
            confidence=float(d.get("confidence", 0)),
            source=d.get("source", ""),
            column=d.get("column", ""),
        )
        er.gnd_id = d.get("gnd_id", "")
        er.gnd_preferred = d.get("gnd_preferred", "")
        er.reviewer_note = d.get("reviewer_note", "")
        er.editor_note = d.get("editor_note", "")
        er.reviewed_at = d.get("reviewed_at", "")
        return er


# Alias for backward compatibility
CuratedEntity = EntityReview


# ---------------------------------------------------------------------------
# CuratedDate — EDTF normalization result
# ---------------------------------------------------------------------------

@dataclass
class CuratedDate:
    """One date normalization result stored in the workspace."""
    original: str
    edtf: str = ""
    confidence: float = 0.0
    method: str = ""
    record_id: str = ""
    column: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "original": self.original,
            "edtf": self.edtf,
            "confidence": self.confidence,
            "method": self.method,
            "record_id": self.record_id,
            "column": self.column,
            "note": self.note,
        }

    @staticmethod
    def from_dict(d: dict) -> "CuratedDate":
        return CuratedDate(
            original=d.get("original", ""),
            edtf=d.get("edtf", ""),
            confidence=float(d.get("confidence", 0)),
            method=d.get("method", ""),
            record_id=d.get("record_id", ""),
            column=d.get("column", ""),
            note=d.get("note", ""),
        )


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

@dataclass
class ImageAnalysisResult:
    """Persisted image analysis result from vision AI."""
    image_id: str
    filename: str = ""
    media_type: str = ""
    size_bytes: int = 0
    width: int | None = None
    height: int | None = None
    hash_sha256: str = ""
    exif_subset: dict = field(default_factory=dict)
    analyzed: bool = False
    result: dict = field(default_factory=dict)
    model: str = ""
    analyzed_at: str = ""
    record_id: str = ""
    review_status: ImageReviewStatus = ImageReviewStatus.PENDING
    review_comment: str = ""
    reviewer: str = ""
    prompt_name: str = ""
    prompt_version: str = ""
    review_note: str = ""
    reviewed_at: str = ""

    @property
    def confidence(self) -> float:
        if isinstance(self.result, dict):
            try:
                return float(self.result.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    @property
    def is_reviewed(self) -> bool:
        return bool(self.reviewed_at and self.review_status != ImageReviewStatus.PENDING)

    @property
    def provenance(self) -> dict:
        return {
            "source": "vision_ai",
            "model": self.model,
            "analyzed_at": self.analyzed_at,
            "reviewed_at": self.reviewed_at,
            "reviewer": self.reviewer,
        }

    def update_review(
        self,
        *,
        status: ImageReviewStatus | str,
        comment: str = "",
        reviewer: str = "",
        result_updates: dict | None = None,
    ) -> None:
        self.review_status = ImageReviewStatus(status) if isinstance(status, str) else status
        self.review_comment = comment
        self.reviewer = reviewer
        if result_updates:
            if not isinstance(self.result, dict):
                self.result = {}
            self.result.update(result_updates)
        self.reviewed_at = datetime.utcnow().isoformat()
    def to_dict(self) -> dict:
        return {
            "image_id": self.image_id,
            "filename": self.filename,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "width": self.width,
            "height": self.height,
            "hash_sha256": self.hash_sha256,
            "exif_subset": self.exif_subset,
            "analyzed": self.analyzed,
            "result": self.result,
            "model": self.model,
            "analyzed_at": self.analyzed_at,
            "record_id": self.record_id,
            "review_comment": self.review_comment,
            "reviewer": self.reviewer,
            "prompt_name": self.prompt_name,
            "prompt_version": self.prompt_version,
            "review_status": self.review_status.value,
            "review_note": self.review_note,
            "reviewed_at": self.reviewed_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "ImageAnalysisResult":
        return ImageAnalysisResult(
            image_id=d.get("image_id", ""),
            filename=d.get("filename", ""),
            media_type=d.get("media_type", ""),
            size_bytes=int(d.get("size_bytes", 0) or 0),
            width=d.get("width"),
            height=d.get("height"),
            hash_sha256=d.get("hash_sha256", ""),
            exif_subset=d.get("exif_subset", {}) or {},
            analyzed=d.get("analyzed", False),
            result=d.get("result", {}),
            model=d.get("model", ""),
            analyzed_at=d.get("analyzed_at", ""),
            record_id=d.get("record_id", ""),
            review_status=ImageReviewStatus(d.get("review_status", "pending")),
            review_comment=d.get("review_comment", ""),
            reviewer=d.get("reviewer", ""),
            prompt_name=d.get("prompt_name", ""),
            prompt_version=d.get("prompt_version", ""),
            review_note=d.get("review_note", ""),
            reviewed_at=d.get("reviewed_at", ""),
        )


class Workspace:
    """
    Central state for one curation project.

    Typical lifecycle:
        ws = Workspace.create("GIUB Hauptsammlung")
        ws.set_field_mapping([FieldMapping(...), ...])
        ws.add_entities(entities)
        json_str = ws.to_json()
    """

    def __init__(
        self,
        name: str = "",
        created_at: str = "",
        updated_at: str = "",
        source_file: str = "",
        id_column: str = "record_id",
    ):
        self.name = name
        self.created_at = created_at or datetime.utcnow().isoformat()
        self.updated_at = updated_at or datetime.utcnow().isoformat()
        self.source_file = source_file
        self.id_column = id_column

        # Internal storage
        self._field_mapping: list[FieldMapping] = []
        self._field_mapping_raw: dict | None = None
        self._dictionary: list[DictionaryEntry] = []
        self.entity_reviews: list[EntityReview] = []
        self.dates: list[CuratedDate] = []
        self.notes: str = ""
        self.model_text: str = ""
        self.model_vision: str = ""
        self.extras: dict[str, Any] = {}
        self.source_files: list[str] = []
        self.ai_runs: list[dict] = []
        self.image_analyses: list[ImageAnalysisResult] = []

    @property
    def field_mapping(self):
        """Return field_mapping. Supports both list[FieldMapping] and dict access."""
        if self._field_mapping_raw is not None:
            return self._field_mapping_raw
        return self._field_mapping

    @field_mapping.setter
    def field_mapping(self, value):
        """Accept both list[FieldMapping] and dict[str, tuple] for field_mapping."""
        if isinstance(value, dict):
            self._field_mapping_raw = value
            self._field_mapping = []
            for col, val in value.items():
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    self._field_mapping.append(FieldMapping(
                        csv_column=col, label=val[0], goobi_type=val[1],
                    ))
                elif isinstance(val, FieldMapping):
                    self._field_mapping.append(val)
        elif isinstance(value, list):
            self._field_mapping_raw = None
            self._field_mapping = value
        else:
            self._field_mapping = value

    @property
    def dictionary(self) -> list[DictionaryEntry]:
        return self._dictionary

    @dictionary.setter
    def dictionary(self, value):
        if isinstance(value, dict):
            self._dictionary = list(value.values())
        elif isinstance(value, list):
            self._dictionary = value
        else:
            self._dictionary = value

    @property
    def entities(self) -> list[EntityReview]:
        """Alias for entity_reviews."""
        return self.entity_reviews

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
        for m in self._field_mapping:
            if m.csv_column == csv_column:
                return m
        return None

    def add_or_update_mapping(self, mapping: FieldMapping) -> None:
        for i, m in enumerate(self._field_mapping):
            if m.csv_column == mapping.csv_column:
                self._field_mapping[i] = mapping
                self._touch()
                return
        self._field_mapping.append(mapping)
        self._touch()

    def active_mappings(self) -> list[FieldMapping]:
        """Return only enabled, non-ignored mappings."""
        return [m for m in self._field_mapping if not m.is_ignored]

    # ------------------------------------------------------------------
    # Dictionary helpers
    # ------------------------------------------------------------------

    def add_entry(self, entry: DictionaryEntry) -> None:
        for i, e in enumerate(self._dictionary):
            if e.term.lower() == entry.term.lower():
                self._dictionary[i] = entry
                self._touch()
                return
        self._dictionary.append(entry)
        self._touch()

    def add_to_dictionary(self, entries: list[dict]) -> int:
        """Add dictionary entries from dicts. Skips duplicates by term."""
        existing = {e.term.lower() for e in self._dictionary}
        added = 0
        for d in entries:
            term = d.get("term", "")
            if term.lower() not in existing:
                self._dictionary.append(DictionaryEntry(
                    term=term,
                    gnd_id=d.get("gnd_id", ""),
                    gnd_type=d.get("category", d.get("gnd_type", "")),
                    source=d.get("source", "manual"),
                ))
                existing.add(term.lower())
                added += 1
        self._touch()
        return added

    def lookup(self, term: str) -> DictionaryEntry | None:
        for e in self._dictionary:
            if e.term.lower() == term.lower():
                return e
        return None

    def lookup_gnd(self, gnd_id: str) -> DictionaryEntry | None:
        for e in self._dictionary:
            if e.gnd_id == gnd_id:
                return e
        return None

    # ------------------------------------------------------------------
    # Entity helpers
    # ------------------------------------------------------------------

    def add_entities(self, entities: list[dict], replace: bool = False) -> int:
        """
        Add entity dicts to the review queue.
        Skips exact duplicates (same text+type+record_id), but updates
        confidence if the new entry has higher confidence.
        """
        if replace:
            self.entity_reviews = []

        existing: dict[tuple, int] = {}
        for i, r in enumerate(self.entity_reviews):
            existing[(r.text.lower(), r.entity_type, r.record_id)] = i

        added = 0
        for e in entities:
            etype = e.get("type", e.get("entity_type", ""))
            key = (e["text"].lower(), etype, e.get("record_id", ""))
            conf = float(e.get("confidence", 0))
            if key in existing:
                idx = existing[key]
                if conf > self.entity_reviews[idx].confidence:
                    self.entity_reviews[idx].confidence = conf
                    self.entity_reviews[idx].source = e.get("source", "")
            else:
                self.entity_reviews.append(EntityReview(
                    text=e["text"],
                    entity_type=etype,
                    record_id=e.get("record_id", ""),
                    confidence=conf,
                    source=e.get("source", ""),
                    gnd_id=e.get("gnd_id") or "",
                    gnd_preferred=e.get("gnd_preferred") or "",
                ))
                existing[key] = len(self.entity_reviews) - 1
                added += 1
        self._touch()
        return added

    def update_entity(self, index: int, updates: dict) -> bool:
        """Update an entity at the given index."""
        if 0 <= index < len(self.entity_reviews):
            er = self.entity_reviews[index]
            for k, v in updates.items():
                if k == "status":
                    er.status = ReviewStatus(v) if isinstance(v, str) else v
                elif hasattr(er, k):
                    setattr(er, k, v)
            self._touch()
            return True
        return False

    def entities_by_status(self) -> dict[str, int]:
        """Return count of entities per status."""
        stats: dict[str, int] = {s.value: 0 for s in ReviewStatus}
        for r in self.entity_reviews:
            stats[r.status.value] += 1
        return stats

    def unique_entities(self) -> list[EntityReview]:
        """Deduplicated entities, keeping highest confidence."""
        best: dict[tuple, EntityReview] = {}
        for e in self.entity_reviews:
            key = (e.text.lower(), e.entity_type)
            if key not in best or e.confidence > best[key].confidence:
                best[key] = e
        return list(best.values())

    def reviews_by_status(self, status: ReviewStatus) -> list[EntityReview]:
        return [r for r in self.entity_reviews if r.status == status]

    def review_stats(self) -> dict[str, int]:
        stats: dict[str, int] = {s.value: 0 for s in ReviewStatus}
        for r in self.entity_reviews:
            stats[r.status.value] += 1
        stats["total"] = len(self.entity_reviews)
        return stats

    # ------------------------------------------------------------------
    # Date helpers
    # ------------------------------------------------------------------

    def add_dates(self, dates: list[dict], replace: bool = False) -> int:
        """Add EDTF date results."""
        if replace:
            self.dates = []
        added = 0
        for d in dates:
            self.dates.append(CuratedDate(
                original=d.get("original", ""),
                edtf=d.get("edtf", ""),
                confidence=float(d.get("confidence", 0)),
                method=d.get("method", ""),
                record_id=d.get("record_id", ""),
                column=d.get("column", ""),
                note=d.get("note", ""),
            ))
            added += 1
        self._touch()
        return added

    # ------------------------------------------------------------------
    # Image analysis helpers
    # ------------------------------------------------------------------

    def save_image_analysis(self, result: ImageAnalysisResult) -> None:
        """Add or update an image analysis result."""
        for i, existing in enumerate(self.image_analyses):
            if existing.image_id == result.image_id:
                self.image_analyses[i] = result
                self._touch()
                return
        self.image_analyses.append(result)
        self._touch()

    def get_image_analysis(self, image_id: str) -> ImageAnalysisResult | None:
        for r in self.image_analyses:
            if r.image_id == image_id:
                return r
        return None

    def image_review_stats(self) -> dict[str, int]:
        stats: dict[str, int] = {s.value: 0 for s in ImageReviewStatus}
        for r in self.image_analyses:
            stats[r.review_status.value] += 1
        stats["total"] = len(self.image_analyses)
        return stats

    def reviewed_image_analyses(self, status: ImageReviewStatus | None = None) -> list[ImageAnalysisResult]:
        if status is None:
            return list(self.image_analyses)
        return [r for r in self.image_analyses if r.review_status == status]

    # ------------------------------------------------------------------
    # AI run logging
    # ------------------------------------------------------------------

    def log_ai_run(
        self, task: str, model: str,
        total: int = 0, succeeded: int = 0, duration: float = 0,
        prompt_name: str = "", prompt_version: str = "",
    ) -> None:
        self.ai_runs.append({
            "task": task, "model": model,
            "total": total, "succeeded": succeeded,
            "duration": duration,
            "prompt_name": prompt_name,
            "prompt_version": prompt_version,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def image_review_stats(self) -> dict[str, int]:
        stats = {"pending": 0, "approved": 0, "rejected": 0, "total": len(self.image_analyses)}
        for result in self.image_analyses:
            status = result.review_status or "pending"
            if status not in stats:
                continue
            stats[status] += 1
        return stats

    def has_pending_ai_suggestions(self) -> bool:
        return any((r.review_status or "pending") == "pending" for r in self.image_analyses)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def to_summary(self) -> dict:
        """Return a summary dict for API responses."""
        return {
            "name": self.name,
            "entity_count": len(self.entity_reviews),
            "date_count": len(self.dates),
            "dictionary_count": len(self._dictionary),
            "mapping_count": len(self._field_mapping),
            "entity_status": self.entities_by_status(),
            "ai_runs": len(self.ai_runs),
            "image_review": self.image_review_stats(),
            "source_files": self.source_files,
            "image_analysis_count": len(self.image_analyses),
            "image_review_status": self.image_review_stats(),
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _touch(self) -> None:
        self.updated_at = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        # Serialize field_mapping
        if self._field_mapping_raw is not None:
            fm_ser = {k: list(v) if isinstance(v, tuple) else v
                      for k, v in self._field_mapping_raw.items()}
        else:
            fm_ser = [m.to_dict() for m in self._field_mapping]

        return {
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_file": self.source_file,
            "source_files": self.source_files,
            "id_column": self.id_column,
            "field_mapping": fm_ser,
            "dictionary": [e.to_dict() for e in self._dictionary],
            "entity_reviews": [r.to_dict() for r in self.entity_reviews],
            "dates": [d.to_dict() for d in self.dates],
            "ai_runs": self.ai_runs,
            "image_analyses": [r.to_dict() for r in self.image_analyses],
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
            name=d.get("name", ""),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            source_file=d.get("source_file", ""),
            id_column=d.get("id_column", "record_id"),
        )
        # Field mapping: support both list and dict formats
        fm = d.get("field_mapping", [])
        if isinstance(fm, list):
            ws._field_mapping = [FieldMapping.from_dict(m) for m in fm]
        elif isinstance(fm, dict):
            ws.field_mapping = fm

        # Dictionary: support both list and dict formats
        dict_data = d.get("dictionary", [])
        if isinstance(dict_data, list):
            ws._dictionary = [DictionaryEntry.from_dict(e) for e in dict_data]
        elif isinstance(dict_data, dict):
            ws._dictionary = [
                DictionaryEntry.from_dict(v) for v in dict_data.values()
            ]

        ws.entity_reviews = [
            EntityReview.from_dict(r) for r in d.get("entity_reviews", [])
        ]
        ws.dates = [
            CuratedDate.from_dict(dt) for dt in d.get("dates", [])
        ]
        ws.ai_runs = d.get("ai_runs", [])
        ws.image_analyses = [
            ImageAnalysisResult.from_dict(r) for r in d.get("image_analyses", [])
        ]
        ws.source_files = d.get("source_files", [])
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
