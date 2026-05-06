"""
GND (Gemeinsame Normdatei) Enrichment.

Integrates authority data from the GND (Deutsche Nationalbibliothek)
into metadata records.

Two data paths:
1. Pre-enriched CSV (GIUBMaster_locations_gnd_merged.csv style):
   parse_gnd_columns() extracts GND IDs from the flattened wide format.

2. Live API (LobidAPI): LobidGNDClient makes HTTP calls to lobid.org.
   This path requires network access and is skipped in offline mode.

CONFIDENCE PARSING:
The real CSV stores confidence as "70%", "85%", etc. — this module
normalises those to 0.0–1.0 floats throughout.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from urllib.request import Request, urlopen
from urllib.parse import quote

import pandas as pd

from kwb.core.workspace import DictionaryEntry

logger = logging.getLogger(__name__)

LOBID_BASE = "https://lobid.org/gnd/search"


# ---------------------------------------------------------------------------
# Confidence normalisation
# ---------------------------------------------------------------------------

def parse_confidence(value: str | float | None) -> float:
    """
    Convert confidence to float in [0.0, 1.0].

    Handles:
    - "85%" → 0.85
    - "0.85" → 0.85
    - 0.85 → 0.85
    - None / "" → 0.0
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 100.0 if v > 1.0 else v
    s = str(value).strip()
    if not s:
        return 0.0
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# GND match dataclass
# ---------------------------------------------------------------------------

@dataclass
class GNDMatch:
    """One resolved GND authority match."""
    term: str
    gnd_id: str
    preferred_name: str
    gnd_type: str = ""
    alternatives: list[str] = field(default_factory=list)
    confidence: float = 1.0
    source: str = "csv"      # "csv" | "lobid" | "llm"
    reasoning: str = ""
    record_id: str = ""

    @property
    def uri(self) -> str:
        return f"http://d-nb.info/gnd/{self.gnd_id}" if self.gnd_id else ""

    def to_dictionary_entry(self) -> DictionaryEntry:
        return DictionaryEntry(
            term=self.preferred_name or self.term,
            gnd_id=self.gnd_id,
            gnd_preferred=self.preferred_name,
            gnd_type=self.gnd_type,
            gnd_uri=self.uri,
            alternatives=self.alternatives,
            confidence=self.confidence,
            source=self.source,
        )


# ---------------------------------------------------------------------------
# Configurable named-entity schema (CORE-ENH-05, Issue #121)
# ---------------------------------------------------------------------------

@dataclass
class NamedEntitySchema:
    """
    Configurable schema for wide-format GND-merged CSVs.

    Different GLAM collections use different naming conventions for their
    flattened named-entity columns. This class lets callers override the
    column-naming pattern instead of relying on the GIUB-specific
    `named_entity_N` prefix.

    All patterns use ``{n}`` as a placeholder for the slot number (1, 2, …).

    Default values match the GIUB master CSV.
    """
    term_pattern: str = "named_entity_{n}"
    id_pattern: str = "named_entity_{n}_gnd_id"
    preferred_pattern: str = "named_entity_{n}_gnd_preferredName"
    confidence_pattern: str = "named_entity_{n}_gnd_konfidenz"
    type_pattern: str = "named_entity_{n}_gnd_type"
    alternatives_pattern: str = "named_entity_{n}_gnd_alternativen"
    record_id_column: str = "record_id"

    def term_col(self, n: int) -> str:
        return self.term_pattern.format(n=n)

    def id_col(self, n: int) -> str:
        return self.id_pattern.format(n=n)

    def preferred_col(self, n: int) -> str:
        return self.preferred_pattern.format(n=n)

    def confidence_col(self, n: int) -> str:
        return self.confidence_pattern.format(n=n)

    def type_col(self, n: int) -> str:
        return self.type_pattern.format(n=n)

    def alternatives_col(self, n: int) -> str:
        return self.alternatives_pattern.format(n=n)

    def detect_max_entities(self, df: pd.DataFrame) -> int:
        """Return the highest slot number N for which id_col(N) exists in df."""
        n = 0
        while self.id_col(n + 1) in df.columns:
            n += 1
        return n


# Default schema preserves backward compatibility with GIUB master CSV.
DEFAULT_NAMED_ENTITY_SCHEMA = NamedEntitySchema()


# ---------------------------------------------------------------------------
# Parse pre-enriched CSV (wide format: named_entity_N_gnd_* columns)
# ---------------------------------------------------------------------------

def parse_gnd_columns(
    df: pd.DataFrame,
    max_entities: int | None = None,
    schema: NamedEntitySchema | None = None,
) -> list[GNDMatch]:
    """
    Extract GND matches from the wide-format GND-merged CSV.

    Args:
        df: DataFrame with named-entity columns (wide format).
        max_entities: Upper bound on slot numbers. If None, auto-detected
            from the actual columns present in df.
        schema: NamedEntitySchema describing the column patterns. Defaults
            to GIUB-style ``named_entity_N_gnd_*``.

    Returns list of GNDMatch for all entities that have a GND ID.
    """
    schema = schema or DEFAULT_NAMED_ENTITY_SCHEMA
    if max_entities is None:
        max_entities = schema.detect_max_entities(df)
        if max_entities == 0:
            return []

    matches: list[GNDMatch] = []

    for _, row in df.iterrows():
        record_id = str(row.get(schema.record_id_column, ""))

        for n in range(1, max_entities + 1):
            term_col = schema.term_col(n)
            id_col = schema.id_col(n)

            if id_col not in df.columns:
                break  # no more entity columns

            gnd_id = row.get(id_col)
            if pd.isna(gnd_id) or not str(gnd_id).strip():
                continue

            term = str(row.get(term_col, "")).strip() if not pd.isna(row.get(term_col, "")) else ""
            preferred = str(row.get(schema.preferred_col(n), "") or "").strip()
            gnd_type = str(row.get(schema.type_col(n), "") or "").strip()
            conf_raw = row.get(schema.confidence_col(n))
            confidence = parse_confidence(conf_raw)

            alts_raw = row.get(schema.alternatives_col(n))
            alternatives: list[str] = []
            if pd.notna(alts_raw) and str(alts_raw).strip():
                alternatives = [a.strip() for a in str(alts_raw).split(";") if a.strip()]

            matches.append(GNDMatch(
                term=term,
                gnd_id=str(gnd_id).strip(),
                preferred_name=preferred or term,
                gnd_type=gnd_type,
                alternatives=alternatives,
                confidence=confidence,
                source="csv",
                record_id=record_id,
            ))

    return matches


def build_dictionary_from_gnd_csv(df: pd.DataFrame) -> dict[str, DictionaryEntry]:
    """
    Build a Normdaten-Wörterbuch from a GND-merged CSV.

    Merges duplicate terms by keeping the highest-confidence match.
    Returns {term.lower(): DictionaryEntry}.
    """
    matches = parse_gnd_columns(df)
    best: dict[str, GNDMatch] = {}

    for m in matches:
        key = m.preferred_name.lower() or m.term.lower()
        if key not in best or m.confidence > best[key].confidence:
            best[key] = m

    return {k: v.to_dictionary_entry() for k, v in best.items()}


# ---------------------------------------------------------------------------
# Low-confidence flagging
# ---------------------------------------------------------------------------

def flag_low_confidence(
    df: pd.DataFrame,
    threshold: float = 0.75,
    max_entities: int | None = None,
    schema: NamedEntitySchema | None = None,
) -> list[dict]:
    """
    Return records/entities where GND confidence is below threshold.

    Useful for the GUI's review queue: "here are 30% of matches that need
    human verification".

    Args:
        df: DataFrame with named-entity columns (wide format).
        threshold: Minimum acceptable confidence; matches below get flagged.
        max_entities: Upper bound on slot numbers. If None, auto-detected.
        schema: NamedEntitySchema describing the column patterns. Defaults
            to GIUB-style ``named_entity_N_gnd_*``.
    """
    schema = schema or DEFAULT_NAMED_ENTITY_SCHEMA
    if max_entities is None:
        max_entities = schema.detect_max_entities(df)
        if max_entities == 0:
            return []

    flags = []
    for _, row in df.iterrows():
        record_id = str(row.get(schema.record_id_column, ""))
        for n in range(1, max_entities + 1):
            id_col = schema.id_col(n)
            if id_col not in df.columns:
                break
            gnd_id = row.get(id_col)
            if pd.isna(gnd_id) or not str(gnd_id).strip():
                continue
            conf = parse_confidence(row.get(schema.confidence_col(n)))
            if conf < threshold:
                flags.append({
                    "record_id": record_id,
                    "term": str(row.get(schema.term_col(n), "")),
                    "gnd_id": str(gnd_id),
                    "confidence": conf,
                    "slot": n,
                })
    return flags


# ---------------------------------------------------------------------------
# Live Lobid API client (requires network)
# ---------------------------------------------------------------------------

class LobidGNDClient:
    """
    Thin client for https://lobid.org/gnd API.

    Usage:
        client = LobidGNDClient()
        if client.is_available():
            matches = client.search("Berlin", type="PlaceOrGeographicName")
    """

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            req = Request(f"{LOBID_BASE}?q=test&size=1&format=json")
            with urlopen(req, timeout=self.timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def search(
        self,
        term: str,
        entity_type: str = "",
        size: int = 5,
    ) -> list[GNDMatch]:
        """
        Search GND for a term.

        Returns up to `size` matches, sorted by lobid score.
        Returns [] on any network error (offline-safe).
        """
        params = f"q={quote(term)}&size={size}&format=json"
        if entity_type:
            params += f"&filter=type:{quote(entity_type)}"

        url = f"{LOBID_BASE}?{params}"
        try:
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning(f"Lobid API unavailable for '{term}': {e}")
            return []

        results = []
        for item in data.get("member", []):
            gnd_id = item.get("gndIdentifier", "")
            preferred = item.get("preferredName", "")
            types = item.get("type", [])
            alts = item.get("variantName", [])

            results.append(GNDMatch(
                term=term,
                gnd_id=gnd_id,
                preferred_name=preferred,
                gnd_type=next((t for t in types if t != "AuthorityResource"), types[0] if types else ""),
                alternatives=alts[:5],
                confidence=0.8,  # lobid doesn't expose a confidence score
                source="lobid",
            ))

        return results

    def lookup_id(self, gnd_id: str) -> GNDMatch | None:
        """Fetch a single GND entity by ID."""
        url = f"https://lobid.org/gnd/{quote(gnd_id)}.json"
        try:
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning(f"Lobid lookup for ID {gnd_id!r} failed: {e}")
            return None

        return GNDMatch(
            term=data.get("preferredName", ""),
            gnd_id=gnd_id,
            preferred_name=data.get("preferredName", ""),
            gnd_type=next((t for t in (data.get("type") or []) if t != "AuthorityResource"), (data.get("type") or [""])[0]),
            alternatives=data.get("variantName", [])[:5],
            confidence=1.0,
            source="lobid",
        )


# ---------------------------------------------------------------------------
# GND type filter mapping (NER type → lobid type filter)
# ---------------------------------------------------------------------------

GND_TYPE_FILTER: dict[str, str] = {
    "PER": "Person",
    "ORG": "CorporateBody",
    "LOC": "PlaceOrGeographicName",
    "GPE": "PlaceOrGeographicName",
    "FAC": "BuildingOrMemorial",
    "EVT": "HistoricSingleEventOrEra",
    "WRK": "Work",
    "CON": "SubjectHeading",
}


# ---------------------------------------------------------------------------
# GNDResult — lightweight result dataclass for API/test consumers
# ---------------------------------------------------------------------------

@dataclass
class GNDResult:
    """Simplified GND search result for API responses."""
    gnd_id: str
    preferred_name: str
    gnd_type: str = ""
    alternative_names: list[str] = field(default_factory=list)
    confidence: float = 0.8

    @property
    def uri(self) -> str:
        return f"https://d-nb.info/gnd/{self.gnd_id}" if self.gnd_id else ""

    def to_dict(self) -> dict:
        return {
            "gnd_id": self.gnd_id,
            "preferred_name": self.preferred_name,
            "gnd_type": self.gnd_type,
            "alternative_names": self.alternative_names,
            "uri": self.uri,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Module-level convenience functions (used by routes and tests)
# ---------------------------------------------------------------------------

_default_client = LobidGNDClient()


def gnd_search(
    term: str,
    entity_type: str = "",
    size: int = 5,
) -> list[GNDResult]:
    """Search GND for a term. Returns [] on empty query or network error."""
    if not term or not term.strip():
        return []

    lobid_type = GND_TYPE_FILTER.get(entity_type, entity_type)
    matches = _default_client.search(term, entity_type=lobid_type, size=size)
    return [
        GNDResult(
            gnd_id=m.gnd_id,
            preferred_name=m.preferred_name,
            gnd_type=m.gnd_type,
            alternative_names=m.alternatives,
            confidence=m.confidence,
        )
        for m in matches
    ]


def gnd_lookup(gnd_id: str) -> GNDResult | None:
    """Look up a single GND entity by ID."""
    m = _default_client.lookup_id(gnd_id)
    if m is None:
        return None
    return GNDResult(
        gnd_id=m.gnd_id,
        preferred_name=m.preferred_name,
        gnd_type=m.gnd_type,
        alternative_names=m.alternatives,
        confidence=m.confidence,
    )


def gnd_batch_search(
    terms: list[dict],
    delay: float = 0.5,
) -> list[dict]:
    """Batch GND search for a list of {text, type, record_id} dicts.

    Returns a list of {text, record_id, results, top_match} dicts.
    """
    import time as _time

    if not terms:
        return []

    output = []
    for i, item in enumerate(terms):
        text = item.get("text", "")
        etype = item.get("type", "")
        record_id = item.get("record_id", "")

        try:
            results = gnd_search(text, entity_type=etype)
        except Exception as e:
            logger.warning(f"GND batch search failed for '{text}': {e}")
            results = []

        top = results[0] if results else None
        output.append({
            "text": text,
            "type": etype,
            "record_id": record_id,
            "results": [r.to_dict() for r in results],
            "top_match": top.to_dict() if top else None,
        })

        if delay > 0 and i < len(terms) - 1:
            _time.sleep(delay)

    return output