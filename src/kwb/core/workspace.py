"""
Workspace persistence for Debussy.

Stores all curated data (entities, EDTF results, classifications, dictionaries)
in a single .debussy.json file per project. No database needed.

Design:
- One workspace per loaded dataset group
- All AI results stored with provenance (source, timestamp, model)
- Manual edits tracked (reviewed flag, editor notes)
- Export-ready: everything needed for Goobi XML is here
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

WORKSPACE_VERSION = "1.0"


@dataclass
class CuratedEntity:
    """An entity that has been reviewed/curated."""
    text: str
    entity_type: str          # PER, ORG, LOC, etc.
    confidence: float = 0.0
    reasoning: str = ""
    source: str = ""          # spacy, llm, manual
    record_id: str = ""
    column: str = ""
    # Norm data links
    gnd_id: str = ""
    gnd_preferred: str = ""
    wikidata_id: str = ""
    # Curation
    normalized: str = ""
    status: str = "pending"   # pending, accepted, rejected, edited
    editor_note: str = ""
    timestamp: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.text}||{self.entity_type}"


@dataclass
class CuratedDate:
    """A date normalization result that has been reviewed."""
    original: str
    edtf: str
    confidence: float = 0.0
    method: str = ""
    record_id: str = ""
    column: str = ""
    status: str = "pending"
    editor_note: str = ""


@dataclass
class DictionaryEntry:
    """A term in the subject/term dictionary."""
    term: str
    normalized: str = ""
    gnd_id: str = ""
    gnd_preferred: str = ""
    wikidata_id: str = ""
    category: str = ""        # NER type or subject category
    status: str = "pending"   # pending, confirmed, rejected
    source: str = ""          # ai, manual, gnd-api
    note: str = ""


@dataclass
class Workspace:
    """Complete project workspace — serializable to JSON."""
    version: str = WORKSPACE_VERSION
    name: str = ""
    created: float = field(default_factory=time.time)
    modified: float = field(default_factory=time.time)
    # Source files
    source_files: list[str] = field(default_factory=list)
    # Curated data
    entities: list[CuratedEntity] = field(default_factory=list)
    dates: list[CuratedDate] = field(default_factory=list)
    dictionary: list[DictionaryEntry] = field(default_factory=list)
    # Metadata mapping (for Goobi export)
    field_mapping: dict[str, str] = field(default_factory=dict)
    # Stats
    ai_runs: list[dict] = field(default_factory=list)

    # --- Entity operations ---

    def add_entities(self, entities: list[dict], replace: bool = False):
        """Add entities from NER results. If replace, clear existing first."""
        if replace:
            self.entities = []
        for e in entities:
            ce = CuratedEntity(
                text=e.get("text", ""), entity_type=e.get("type", "CON"),
                confidence=e.get("confidence", 0), reasoning=e.get("reasoning", ""),
                source=e.get("source", ""), record_id=e.get("record_id", ""),
                column=e.get("column", ""),
                gnd_id=e.get("gnd_id", "") or "", gnd_preferred=e.get("gnd_preferred", "") or "",
                wikidata_id=e.get("wikidata_id", "") or "",
                normalized=e.get("normalized", "") or "",
                status="pending", timestamp=time.time(),
            )
            self.entities.append(ce)
        self.modified = time.time()

    def update_entity(self, idx: int, updates: dict) -> bool:
        """Update a single entity by index."""
        if 0 <= idx < len(self.entities):
            e = self.entities[idx]
            for k, v in updates.items():
                if hasattr(e, k):
                    setattr(e, k, v)
            e.timestamp = time.time()
            self.modified = time.time()
            return True
        return False

    def entities_by_status(self) -> dict[str, int]:
        counts = {}
        for e in self.entities:
            counts[e.status] = counts.get(e.status, 0) + 1
        return counts

    def unique_entities(self) -> list[CuratedEntity]:
        """Deduplicated, highest confidence per (text, type)."""
        best: dict[str, CuratedEntity] = {}
        for e in self.entities:
            if e.key not in best or e.confidence > best[e.key].confidence:
                best[e.key] = e
        return sorted(best.values(), key=lambda x: (-x.confidence, x.text))

    # --- Date operations ---

    def add_dates(self, dates: list[dict], replace: bool = False):
        if replace:
            self.dates = []
        for d in dates:
            self.dates.append(CuratedDate(
                original=d.get("original", ""), edtf=d.get("edtf", ""),
                confidence=d.get("confidence", 0), method=d.get("method", ""),
                record_id=d.get("record_id", ""), column=d.get("column", ""),
                status="pending",
            ))
        self.modified = time.time()

    def update_date(self, idx: int, updates: dict) -> bool:
        if 0 <= idx < len(self.dates):
            d = self.dates[idx]
            for k, v in updates.items():
                if hasattr(d, k): setattr(d, k, v)
            self.modified = time.time()
            return True
        return False

    # --- Dictionary operations ---

    def add_to_dictionary(self, entries: list[dict]):
        existing = {e.term for e in self.dictionary}
        for d in entries:
            term = d.get("term", "")
            if term and term not in existing:
                self.dictionary.append(DictionaryEntry(
                    term=term, normalized=d.get("normalized", ""),
                    gnd_id=d.get("gnd_id", ""), gnd_preferred=d.get("gnd_preferred", ""),
                    wikidata_id=d.get("wikidata_id", ""),
                    category=d.get("category", ""), status="pending",
                    source=d.get("source", ""), note=d.get("note", ""),
                ))
                existing.add(term)
        self.modified = time.time()

    def update_dictionary_entry(self, idx: int, updates: dict) -> bool:
        if 0 <= idx < len(self.dictionary):
            e = self.dictionary[idx]
            for k, v in updates.items():
                if hasattr(e, k): setattr(e, k, v)
            self.modified = time.time()
            return True
        return False

    # --- AI run logging ---

    def log_ai_run(self, task: str, model: str, total: int, succeeded: int, duration: float = 0):
        self.ai_runs.append({
            "task": task, "model": model, "total": total,
            "succeeded": succeeded, "duration": round(duration, 2),
            "timestamp": time.time(),
        })
        self.modified = time.time()

    # --- Serialization ---

    def save(self, path: str | Path):
        path = Path(path)
        data = {
            "version": self.version, "name": self.name,
            "created": self.created, "modified": self.modified,
            "source_files": self.source_files,
            "entities": [asdict(e) for e in self.entities],
            "dates": [asdict(d) for d in self.dates],
            "dictionary": [asdict(d) for d in self.dictionary],
            "field_mapping": self.field_mapping,
            "ai_runs": self.ai_runs,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Workspace saved: {path} ({len(self.entities)} entities, {len(self.dates)} dates)")

    @classmethod
    def load(cls, path: str | Path) -> Workspace:
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        ws = cls(
            version=data.get("version", "1.0"), name=data.get("name", ""),
            created=data.get("created", 0), modified=data.get("modified", 0),
            source_files=data.get("source_files", []),
            field_mapping=data.get("field_mapping", {}),
            ai_runs=data.get("ai_runs", []),
        )
        for e in data.get("entities", []):
            ws.entities.append(CuratedEntity(**{k: e.get(k, "") for k in CuratedEntity.__dataclass_fields__}))
        for d in data.get("dates", []):
            ws.dates.append(CuratedDate(**{k: d.get(k, "") for k in CuratedDate.__dataclass_fields__}))
        for d in data.get("dictionary", []):
            ws.dictionary.append(DictionaryEntry(**{k: d.get(k, "") for k in DictionaryEntry.__dataclass_fields__}))
        return ws

    def to_summary(self) -> dict:
        return {
            "name": self.name, "source_files": self.source_files,
            "entity_count": len(self.entities),
            "entity_status": self.entities_by_status(),
            "date_count": len(self.dates),
            "dictionary_size": len(self.dictionary),
            "ai_runs": len(self.ai_runs),
            "modified": self.modified,
        }
