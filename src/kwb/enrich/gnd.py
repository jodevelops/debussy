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
import re
from dataclasses import dataclass, field
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
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
# Parse pre-enriched CSV (wide format: named_entity_N_gnd_* columns)
# ---------------------------------------------------------------------------

def parse_gnd_columns(df: pd.DataFrame, max_entities: int = 11) -> list[GNDMatch]:
    """
    Extract GND matches from the wide-format GND-merged CSV.

    Expects columns named:
        named_entity_N, named_entity_N_gnd_id,
        named_entity_N_gnd_preferredName, named_entity_N_gnd_konfidenz,
        named_entity_N_gnd_type, named_entity_N_gnd_alternativen

    for N in 1..max_entities.

    Returns list of GNDMatch for all entities that have a GND ID.
    """
    matches: list[GNDMatch] = []

    for _, row in df.iterrows():
        record_id = str(row.get("record_id", ""))

        for n in range(1, max_entities + 1):
            prefix = f"named_entity_{n}"
            term_col = prefix
            id_col = f"{prefix}_gnd_id"

            if id_col not in df.columns:
                break  # no more entity columns

            gnd_id = row.get(id_col)
            if pd.isna(gnd_id) or not str(gnd_id).strip():
                continue

            term = str(row.get(term_col, "")).strip() if not pd.isna(row.get(term_col, "")) else ""
            preferred = str(row.get(f"{prefix}_gnd_preferredName", "") or "").strip()
            gnd_type = str(row.get(f"{prefix}_gnd_type", "") or "").strip()
            conf_raw = row.get(f"{prefix}_gnd_konfidenz")
            confidence = parse_confidence(conf_raw)

            alts_raw = row.get(f"{prefix}_gnd_alternativen")
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
    max_entities: int = 11,
) -> list[dict]:
    """
    Return records/entities where GND confidence is below threshold.

    Useful for the GUI's review queue: "here are 30% of matches that need
    human verification".
    """
    flags = []
    for _, row in df.iterrows():
        record_id = str(row.get("record_id", ""))
        for n in range(1, max_entities + 1):
            id_col = f"named_entity_{n}_gnd_id"
            if id_col not in df.columns:
                break
            gnd_id = row.get(id_col)
            if pd.isna(gnd_id) or not str(gnd_id).strip():
                continue
            conf = parse_confidence(row.get(f"named_entity_{n}_gnd_konfidenz"))
            if conf < threshold:
                flags.append({
                    "record_id": record_id,
                    "term": str(row.get(f"named_entity_{n}", "")),
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
        except (HTTPError, URLError, TimeoutError) as e:
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
                gnd_type=types[0] if types else "",
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
            gnd_type=(data.get("type") or [""])[0],
            alternatives=data.get("variantName", [])[:5],
            confidence=1.0,
            source="lobid",
        )
# --- Compatibility wrappers expected by kwb.api.app ---

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

LOBID_BASE = "https://lobid.org/gnd/search"

@dataclass
class GNDResult:
    gnd_id: str
    preferred_name: str
    gnd_type: str = ""
    alternative_names: list[str] = None
    description: str = ""
    uri: str = ""
    score: float = 0.0

    def __post_init__(self):
        if self.alternative_names is None:
            self.alternative_names = []
        if not self.uri and self.gnd_id:
            self.uri = f"https://d-nb.info/gnd/{self.gnd_id}"

    def to_dict(self) -> dict:
        return {
            "gnd_id": self.gnd_id,
            "preferred_name": self.preferred_name,
            "type": self.gnd_type,
            "alternative_names": self.alternative_names,
            "description": self.description,
            "uri": self.uri,
            "score": self.score,
        }

def gnd_search(query: str, entity_type: str = "", size: int = 5, timeout: float = 5.0) -> list[GNDResult]:
    if not query or not str(query).strip():
        return []
    params = {"q": str(query).strip(), "size": str(size), "format": "json"}
    url = f"{LOBID_BASE}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Debussy/compat"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    out: list[GNDResult] = []
    for item in data.get("member", []):
        gid = item.get("gndIdentifier", "")
        if not gid:
            continue
        preferred = item.get("preferredName", "")
        types = item.get("type", [])
        gtype = next((t for t in types if t != "AuthorityResource"), "")
        alts = [v for v in item.get("variantName", []) if isinstance(v, str)][:5]
        out.append(GNDResult(gnd_id=gid, preferred_name=preferred, gnd_type=gtype, alternative_names=alts))
    return out

def gnd_batch_search(terms: list[dict[str, str]], delay: float = 0.0) -> list[dict]:
    results = []
    for item in terms:
        text = item.get("text", "")
        etype = item.get("type", "")
        hits = gnd_search(text, entity_type=etype, size=3)
        results.append({
            "text": text,
            "type": etype,
            "record_id": item.get("record_id", ""),
            "results": [h.to_dict() for h in hits],
            "top_match": hits[0].to_dict() if hits else None,
        })
    return results