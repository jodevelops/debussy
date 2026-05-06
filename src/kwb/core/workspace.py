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
import uuid as _uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from kwb.core.models import Provenance, ReviewStatus
from kwb.core.utils import utc_now_iso

__all__ = [
    "GoobiMetadataType", "FieldMapping",
    "DictionaryType", "DictionaryEntry",
    "ReviewStatus", "ImageReviewStatus",
    "AuthorityCandidate", "EntityReview", "CuratedEntity",
    "CuratedDate", "ImageAnalysisResult", "Workspace",
]


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

class DictionaryType(str, Enum):
    """Types for typed dictionaries."""
    PLACE = "place"
    PERSON = "person"
    INSTITUTION = "institution"
    CONCEPT = "concept"
    EVENT = "event"
    WORK = "work"
    OTHER = "other"

    @property
    def label_de(self) -> str:
        return {
            "place": "Orte", "person": "Personen",
            "institution": "Institutionen", "concept": "Konzepte",
            "event": "Ereignisse", "work": "Werke", "other": "Sonstige",
        }[self.value]

    @staticmethod
    def from_entity_type(entity_type: str) -> "DictionaryType":
        """Map NER entity types to dictionary types."""
        mapping = {
            "PER": DictionaryType.PERSON,
            "ORG": DictionaryType.INSTITUTION,
            "LOC": DictionaryType.PLACE,
            "GPE": DictionaryType.PLACE,
            "FAC": DictionaryType.PLACE,
            "EVT": DictionaryType.EVENT,
            "WRK": DictionaryType.WORK,
            "CON": DictionaryType.CONCEPT,
            "ETH": DictionaryType.CONCEPT,
            "DAT": DictionaryType.OTHER,
            "TOP": DictionaryType.CONCEPT,
        }
        return mapping.get(entity_type, DictionaryType.OTHER)


@dataclass
class DictionaryEntry:
    """A single normed term with authority mapping, record provenance, and type."""
    term: str                          # Original/preferred display term
    entry_id: str = ""                 # Unique ID (auto-generated UUID)
    entity_type: str = ""              # DictionaryType value: place/person/institution/…
    preferred_name: str = ""           # Vorzugsbenennung
    record_ids: list[str] = field(default_factory=list)  # Records where this term appears
    gnd_id: str = ""                   # e.g. "4074335-4"
    gnd_preferred: str = ""            # GND preferred name
    gnd_type: str = ""                 # "Geographic", "Person", "SubjectHeading", …
    gnd_uri: str = ""                  # full URI
    wikidata_id: str = ""              # "Q64"
    geonames_id: str = ""             # GeoNames ID
    alternatives: list[str] = field(default_factory=list)
    confidence: float = 1.0
    source: str = "manual"            # "manual" | "api" | "llm" | "ner" | "ocr"
    note: str = ""
    term_normalized: str = ""          # NFC + whitespace-collapsed form
    term_source: str = ""              # "ocr" | "metadata" | "manual"
    model_source: str = ""             # AI model used (e.g. "qwen3-coder")
    last_edited: str = ""              # ISO timestamp of last edit

    def __post_init__(self):
        if not self.entry_id:
            self.entry_id = str(_uuid.uuid4())[:8]

    @property
    def has_authority(self) -> bool:
        return bool(self.gnd_id or self.wikidata_id or self.geonames_id)

    def provenance(self) -> Provenance:
        """Canonical provenance dict (CORE-ENH-03)."""
        return {
            "source": self.source,
            "method": self.source,  # source doubles as method here
            "model": self.model_source,
            "extracted_at": "",  # not tracked at extraction time
            "reviewed_at": self.last_edited,
            "reviewer": "",
            "note": self.note,
        }

    def add_record_id(self, record_id: str) -> None:
        """Add a record_id if not already present."""
        if record_id and record_id not in self.record_ids:
            self.record_ids.append(record_id)

    def merge_record_ids(self, other_ids: list[str]) -> None:
        """Merge record IDs from another source."""
        for rid in other_ids:
            self.add_record_id(rid)

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "entry_id": self.entry_id,
            "entity_type": self.entity_type,
            "preferred_name": self.preferred_name,
            "record_ids": self.record_ids,
            "gnd_id": self.gnd_id,
            "gnd_preferred": self.gnd_preferred,
            "gnd_type": self.gnd_type,
            "gnd_uri": self.gnd_uri,
            "wikidata_id": self.wikidata_id,
            "geonames_id": self.geonames_id,
            "alternatives": self.alternatives,
            "confidence": self.confidence,
            "source": self.source,
            "note": self.note,
            "term_normalized": self.term_normalized,
            "term_source": self.term_source,
            "model_source": self.model_source,
            "last_edited": self.last_edited,
        }

    @staticmethod
    def from_dict(d: dict) -> "DictionaryEntry":
        e = DictionaryEntry(term=d.get("term", ""))
        for k, v in d.items():
            if k == "term":
                continue
            if hasattr(e, k):
                setattr(e, k, v)
        return e


# ---------------------------------------------------------------------------
# Entity Review Status
# ---------------------------------------------------------------------------

class ImageReviewStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass
class AuthorityCandidate:
    """An authority-match candidate pending human review."""
    entry_id: str                       # Target DictionaryEntry.entry_id
    candidate_id: str = ""              # Auto UUID
    source: str = ""                    # "gnd" | "wikidata" | "geonames"
    authority_id: str = ""              # GND ID, QID, or GeoNames ID
    preferred_name: str = ""
    authority_type: str = ""            # "Person", "PlaceOrGeographicName", etc.
    uri: str = ""
    score: float = 0.0
    extra: dict = field(default_factory=dict)
    status: ReviewStatus = ReviewStatus.PENDING
    reviewer_note: str = ""
    reviewed_at: str = ""
    # Provenance fields (CORE-ENH-03)
    model: str = ""                     # AI model used (if any)
    extracted_at: str = ""              # When the candidate was discovered
    reviewer: str = ""                  # Who reviewed

    def __post_init__(self):
        if not self.candidate_id:
            self.candidate_id = str(_uuid.uuid4())[:8]

    def accept(self, note: str = "", reviewer: str = "") -> None:
        self.status = ReviewStatus.ACCEPTED
        self.reviewer_note = note
        self.reviewer = reviewer or self.reviewer
        self.reviewed_at = utc_now_iso()

    def reject(self, note: str = "", reviewer: str = "") -> None:
        self.status = ReviewStatus.REJECTED
        self.reviewer_note = note
        self.reviewer = reviewer or self.reviewer
        self.reviewed_at = utc_now_iso()

    def provenance(self) -> Provenance:
        """Canonical provenance dict (CORE-ENH-03)."""
        return {
            "source": self.source,
            "method": "api",  # authority candidates always come from API lookups
            "model": self.model,
            "extracted_at": self.extracted_at,
            "reviewed_at": self.reviewed_at,
            "reviewer": self.reviewer,
            "note": self.reviewer_note,
        }

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "candidate_id": self.candidate_id,
            "source": self.source,
            "authority_id": self.authority_id,
            "preferred_name": self.preferred_name,
            "authority_type": self.authority_type,
            "uri": self.uri,
            "score": self.score,
            "extra": self.extra,
            "status": self.status.value,
            "reviewer_note": self.reviewer_note,
            "reviewed_at": self.reviewed_at,
            "model": self.model,
            "extracted_at": self.extracted_at,
            "reviewer": self.reviewer,
        }

    @staticmethod
    def from_dict(d: dict) -> "AuthorityCandidate":
        return AuthorityCandidate(
            entry_id=d.get("entry_id", ""),
            candidate_id=d.get("candidate_id", ""),
            source=d.get("source", ""),
            authority_id=d.get("authority_id", ""),
            preferred_name=d.get("preferred_name", ""),
            authority_type=d.get("authority_type", ""),
            uri=d.get("uri", ""),
            score=float(d.get("score", 0)),
            extra=d.get("extra", {}),
            status=ReviewStatus(d.get("status", "pending")),
            reviewer_note=d.get("reviewer_note", ""),
            reviewed_at=d.get("reviewed_at", ""),
            model=d.get("model", ""),
            extracted_at=d.get("extracted_at", ""),
            reviewer=d.get("reviewer", ""),
        )


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
    # Provenance fields (CORE-ENH-03)
    model: str = ""                     # AI model used (e.g., "qwen3-coder")
    extracted_at: str = ""              # When the entity was extracted
    reviewer: str = ""                  # Who reviewed

    def __post_init__(self):
        pass

    def accept(self, gnd_id: str = "", gnd_preferred: str = "",
               note: str = "", reviewer: str = "") -> None:
        self.status = ReviewStatus.ACCEPTED
        self.gnd_id = gnd_id
        self.gnd_preferred = gnd_preferred
        self.reviewer_note = note
        self.reviewer = reviewer or self.reviewer
        self.reviewed_at = utc_now_iso()

    def reject(self, note: str = "", reviewer: str = "") -> None:
        self.status = ReviewStatus.REJECTED
        self.reviewer_note = note
        self.reviewer = reviewer or self.reviewer
        self.reviewed_at = utc_now_iso()

    @property
    def dedup_key(self) -> tuple[str, str]:
        return (self.text.lower(), self.entity_type)

    def provenance(self) -> Provenance:
        """Canonical provenance dict (CORE-ENH-03)."""
        # Map source ("llm"/"spacy"/"manual") to method
        method = self.source if self.source in ("llm", "spacy", "rule", "manual") else "ner"
        return {
            "source": self.source,
            "method": method,
            "model": self.model,
            "extracted_at": self.extracted_at,
            "reviewed_at": self.reviewed_at,
            "reviewer": self.reviewer,
            "note": self.editor_note or self.reviewer_note,
        }

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
            "model": self.model,
            "extracted_at": self.extracted_at,
            "reviewer": self.reviewer,
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
            model=d.get("model", ""),
            extracted_at=d.get("extracted_at", ""),
            reviewer=d.get("reviewer", ""),
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
    # Provenance fields (CORE-ENH-03)
    source: str = ""                    # "rule" | "llm" | "hybrid" | "manual"
    model: str = ""                     # AI model used (if any)
    extracted_at: str = ""              # When the date was normalized
    reviewed_at: str = ""               # When reviewed (if any)
    reviewer: str = ""                  # Who reviewed

    def __post_init__(self):
        # Mirror method into source for uniform provenance reads
        if not self.source and self.method:
            self.source = self.method

    def provenance(self) -> Provenance:
        """Canonical provenance dict (CORE-ENH-03)."""
        return {
            "source": self.source or self.method,
            "method": self.method,
            "model": self.model,
            "extracted_at": self.extracted_at,
            "reviewed_at": self.reviewed_at,
            "reviewer": self.reviewer,
            "note": self.note,
        }

    def to_dict(self) -> dict:
        return {
            "original": self.original,
            "edtf": self.edtf,
            "confidence": self.confidence,
            "method": self.method,
            "record_id": self.record_id,
            "column": self.column,
            "note": self.note,
            "source": self.source,
            "model": self.model,
            "extracted_at": self.extracted_at,
            "reviewed_at": self.reviewed_at,
            "reviewer": self.reviewer,
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
            source=d.get("source", ""),
            model=d.get("model", ""),
            extracted_at=d.get("extracted_at", ""),
            reviewed_at=d.get("reviewed_at", ""),
            reviewer=d.get("reviewer", ""),
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

    def provenance(self) -> Provenance:
        """Canonical provenance dict (CORE-ENH-03)."""
        return {
            "source": "vision_ai",
            "method": "llm",
            "model": self.model,
            "extracted_at": self.analyzed_at,
            "reviewed_at": self.reviewed_at,
            "reviewer": self.reviewer,
            "note": self.review_note or self.review_comment,
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
        self.reviewed_at = utc_now_iso()
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
        self.created_at = created_at or utc_now_iso()
        self.updated_at = updated_at or utc_now_iso()
        self.source_file = source_file
        self.id_column = id_column

        # Internal storage — canonical list format only (CORE-BUG-03)
        self._field_mapping: list[FieldMapping] = []
        self._dictionary: list[DictionaryEntry] = []
        self.entity_reviews: list[EntityReview] = []
        self.dates: list[CuratedDate] = []
        self.tasks: list[dict] = []  # CurationTask dicts
        self.custom_mds_fields: list[dict] = []  # Custom MDS field definitions
        self.notes: str = ""
        self.model_text: str = ""
        self.model_vision: str = ""
        self.extras: dict[str, Any] = {}
        self.source_files: list[str] = []
        self.ai_runs: list[dict] = []
        self.image_analyses: list[ImageAnalysisResult] = []
        self.authority_candidates: list[AuthorityCandidate] = []

    @property
    def field_mapping(self) -> list[FieldMapping]:
        """Return field_mapping as list[FieldMapping] (canonical format)."""
        return self._field_mapping

    @field_mapping.setter
    def field_mapping(self, value):
        """
        Accept list[FieldMapping] or legacy dict[str, tuple] format.
        Legacy dict format is converted to canonical list format.
        """
        if isinstance(value, dict):
            # Migrate legacy dict[str, (label, type)] format to list
            self._field_mapping = []
            for col, val in value.items():
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    # Legacy: (label, goobi_type) or [label, goobi_type]
                    self._field_mapping.append(FieldMapping(
                        csv_column=col,
                        label=val[0],
                        goobi_type=val[1],
                    ))
                elif isinstance(val, FieldMapping):
                    self._field_mapping.append(val)
        elif isinstance(value, list):
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
                # Merge record_ids from old entry
                entry.merge_record_ids(e.record_ids)
                if not entry.entry_id:
                    entry.entry_id = e.entry_id
                self._dictionary[i] = entry
                self._touch()
                return
        self._dictionary.append(entry)
        self._touch()

    def add_to_dictionary(self, entries: list[dict]) -> int:
        """Add dictionary entries from dicts. Merges record_ids on duplicates."""
        lookup = {e.term.lower(): i for i, e in enumerate(self._dictionary)}
        added = 0
        for d in entries:
            term = d.get("term", "")
            if not term:
                continue
            record_id = d.get("record_id", "")
            record_ids = d.get("record_ids", [])
            if record_id and record_id not in record_ids:
                record_ids = [record_id] + record_ids

            key = term.lower()
            if key in lookup:
                existing = self._dictionary[lookup[key]]
                existing.merge_record_ids(record_ids)
                # Update entity_type if not set
                if not existing.entity_type and d.get("entity_type"):
                    existing.entity_type = d["entity_type"]
                # Add alternative spelling
                if term not in existing.alternatives and term != existing.term:
                    existing.alternatives.append(term)
            else:
                entity_type = d.get("entity_type", d.get("category", ""))
                if entity_type in ("PER", "ORG", "LOC", "GPE", "FAC",
                                   "EVT", "WRK", "DAT", "ETH", "CON"):
                    entity_type = DictionaryType.from_entity_type(entity_type).value
                entry = DictionaryEntry(
                    term=term,
                    entity_type=entity_type or d.get("gnd_type", ""),
                    gnd_id=d.get("gnd_id", ""),
                    gnd_type=d.get("gnd_type", ""),
                    source=d.get("source", "manual"),
                    record_ids=record_ids,
                    preferred_name=d.get("preferred_name", ""),
                )
                self._dictionary.append(entry)
                lookup[key] = len(self._dictionary) - 1
                added += 1
        self._touch()
        return added

    def lookup(self, term: str) -> DictionaryEntry | None:
        for e in self._dictionary:
            if e.term.lower() == term.lower():
                return e
            if term.lower() in [a.lower() for a in e.alternatives]:
                return e
        return None

    def lookup_gnd(self, gnd_id: str) -> DictionaryEntry | None:
        for e in self._dictionary:
            if e.gnd_id == gnd_id:
                return e
        return None

    def lookup_by_id(self, entry_id: str) -> DictionaryEntry | None:
        """Find a dictionary entry by its unique entry_id."""
        for e in self._dictionary:
            if e.entry_id == entry_id:
                return e
        return None

    def dictionary_by_type(self, entity_type: str) -> list[DictionaryEntry]:
        """Return entries filtered by DictionaryType value."""
        return [e for e in self._dictionary if e.entity_type == entity_type]

    def export_dictionary_json(
        self, entity_type: str | None = None, indent: int = 2,
    ) -> str:
        """Export dictionary (or a typed subset) as JSON string."""
        if entity_type:
            entries = self.dictionary_by_type(entity_type)
        else:
            entries = list(self._dictionary)
        return json.dumps(
            [e.to_dict() for e in entries],
            ensure_ascii=False, indent=indent,
        )

    def export_typed_dictionaries(self) -> dict[str, list[dict]]:
        """Export all dictionaries grouped by entity_type."""
        result: dict[str, list[dict]] = {}
        for e in self._dictionary:
            t = e.entity_type or "other"
            result.setdefault(t, []).append(e.to_dict())
        return result

    def build_dictionary_from_dataframe(
        self,
        df,  # pandas.DataFrame
        columns: list[str],
        entity_type: str = "",
        id_column: str = "",
        source: str = "ingest",
    ) -> int:
        """Build/extend dictionary from unique values in a DataFrame.

        Collects unique terms from the given columns and records which
        record IDs each term appears in.
        """
        entries: list[dict] = []
        for _, row in df.iterrows():
            rid = str(row.get(id_column, "")) if id_column else ""
            for col in columns:
                val = row.get(col)
                if val is None or str(val).strip() in ("", "nan", "NaN"):
                    continue
                # Handle semicolon-separated multi-values
                for part in str(val).split(";"):
                    term = part.strip()
                    if term:
                        entries.append({
                            "term": term,
                            "entity_type": entity_type,
                            "record_id": rid,
                            "source": source,
                        })
        return self.add_to_dictionary(entries)

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
    # Authority candidate helpers
    # ------------------------------------------------------------------

    def add_authority_candidate(self, candidate: AuthorityCandidate) -> None:
        """Add an authority candidate for review."""
        self.authority_candidates.append(candidate)
        self._touch()

    def authority_candidates_for_entry(self, entry_id: str) -> list[AuthorityCandidate]:
        """Return all authority candidates for a given dictionary entry."""
        return [c for c in self.authority_candidates if c.entry_id == entry_id]

    def authority_review_stats(self) -> dict[str, int]:
        """Return count of authority candidates per status."""
        stats: dict[str, int] = {s.value: 0 for s in ReviewStatus}
        for c in self.authority_candidates:
            stats[c.status.value] += 1
        stats["total"] = len(self.authority_candidates)
        return stats

    def accepted_ocr_analyses(self) -> list[ImageAnalysisResult]:
        """Return only accepted OCR image analyses."""
        return [
            r for r in self.image_analyses
            if r.review_status == ImageReviewStatus.ACCEPTED
        ]

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
            "timestamp": utc_now_iso(),
        })

    def has_pending_ai_suggestions(self) -> bool:
        return any(
            r.review_status == ImageReviewStatus.PENDING
            for r in self.image_analyses
        )

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
            "authority_candidates_count": len(self.authority_candidates),
            "authority_review_status": self.authority_review_stats(),
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _touch(self) -> None:
        self.updated_at = utc_now_iso()

    def to_dict(self) -> dict:
        # Serialize field_mapping as list (canonical format, CORE-BUG-03)
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
            "tasks": self.tasks,
            "custom_mds_fields": self.custom_mds_fields,
            "ai_runs": self.ai_runs,
            "image_analyses": [r.to_dict() for r in self.image_analyses],
            "authority_candidates": [c.to_dict() for c in self.authority_candidates],
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
        # Field mapping: migrate legacy dict format to canonical list format (CORE-BUG-03)
        fm = d.get("field_mapping", [])
        if isinstance(fm, list):
            ws._field_mapping = [FieldMapping.from_dict(m) for m in fm]
        elif isinstance(fm, dict):
            # Legacy dict format: convert via property setter
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
        ws.tasks = d.get("tasks", [])
        ws.custom_mds_fields = d.get("custom_mds_fields", [])
        ws.ai_runs = d.get("ai_runs", [])
        ws.image_analyses = [
            ImageAnalysisResult.from_dict(r) for r in d.get("image_analyses", [])
        ]
        ws.authority_candidates = [
            AuthorityCandidate.from_dict(c)
            for c in d.get("authority_candidates", [])
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
