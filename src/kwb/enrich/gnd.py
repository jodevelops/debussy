"""
GND lookup via lobid.org/gnd API.

Free, no API key needed. Returns real GND records with IDs, preferred names,
types, and alternative names.

Usage:
    results = gnd_search("Bern")
    # [{"gnd_id": "4005762-8", "preferred": "Bern", "type": "PlaceOrGeographicName", ...}]
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

LOBID_BASE = "https://lobid.org/gnd/search"
LOBID_ENTITY = "https://lobid.org/gnd"


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
            "gnd_id": self.gnd_id, "preferred_name": self.preferred_name,
            "type": self.gnd_type, "alternative_names": self.alternative_names,
            "description": self.description, "uri": self.uri, "score": self.score,
        }


# GND type mapping for filtering
GND_TYPE_FILTER = {
    "PER": "Person",
    "ORG": "CorporateBody",
    "LOC": "PlaceOrGeographicName",
    "GPE": "PlaceOrGeographicName",
    "FAC": "PlaceOrGeographicName",
    "WRK": "Work",
    "EVT": "SubjectHeading",
    "CON": "SubjectHeading",
}


def gnd_search(
    query: str,
    entity_type: str = "",
    size: int = 5,
    timeout: float = 5.0,
) -> list[GNDResult]:
    """
    Search GND via lobid.org API.

    Args:
        query: Search term
        entity_type: NER type (PER, ORG, LOC...) for type filtering
        size: Max results
        timeout: HTTP timeout in seconds
    """
    if not query or not query.strip():
        return []

    params = {"q": query.strip(), "size": str(size), "format": "json"}

    # Add type filter if we know the entity type
    gnd_type = GND_TYPE_FILTER.get(entity_type, "")
    if gnd_type:
        params["filter"] = f"type:{gnd_type}"

    url = f"{LOBID_BASE}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "Debussy/0.4 (GLAM curation workbench)",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"GND search failed for '{query}': {e}")
        return []

    results = []
    for item in data.get("member", []):
        gnd_id = item.get("gndIdentifier", "")
        if not gnd_id:
            continue

        # Extract type
        types = item.get("type", [])
        gnd_type_str = ""
        for t in types:
            if t not in ("AuthorityResource",):
                gnd_type_str = t
                break

        # Extract preferred name
        preferred = item.get("preferredName", "")

        # Alternative names
        alt_names = []
        for v in item.get("variantName", []):
            if isinstance(v, str):
                alt_names.append(v)

        # Description from various fields
        desc_parts = []
        for field in ("biographicalOrHistoricalInformation", "definition"):
            vals = item.get(field, [])
            if isinstance(vals, list):
                desc_parts.extend(str(v) for v in vals)
            elif isinstance(vals, str):
                desc_parts.append(vals)

        results.append(GNDResult(
            gnd_id=gnd_id, preferred_name=preferred,
            gnd_type=gnd_type_str, alternative_names=alt_names[:5],
            description="; ".join(desc_parts)[:200],
        ))

    return results


def gnd_lookup(gnd_id: str, timeout: float = 5.0) -> GNDResult | None:
    """Fetch a single GND record by ID."""
    url = f"{LOBID_ENTITY}/{gnd_id}.json"
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "Debussy/0.4",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            item = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"GND lookup failed for '{gnd_id}': {e}")
        return None

    types = item.get("type", [])
    gnd_type_str = next((t for t in types if t != "AuthorityResource"), "")

    return GNDResult(
        gnd_id=item.get("gndIdentifier", gnd_id),
        preferred_name=item.get("preferredName", ""),
        gnd_type=gnd_type_str,
        alternative_names=[v for v in item.get("variantName", []) if isinstance(v, str)][:5],
        description="; ".join(str(v) for v in item.get("biographicalOrHistoricalInformation", []))[:200],
    )


def gnd_batch_search(
    terms: list[dict[str, str]],
    delay: float = 0.2,
) -> list[dict]:
    """
    Batch GND search for multiple terms.

    Args:
        terms: [{"text": "Bern", "type": "GPE", "record_id": "r1"}, ...]
        delay: Delay between requests (be polite to lobid.org)

    Returns:
        [{"text": "...", "record_id": "...", "results": [GNDResult.to_dict(), ...]}]
    """
    all_results = []
    for i, item in enumerate(terms):
        text = item.get("text", "")
        etype = item.get("type", "")
        results = gnd_search(text, entity_type=etype, size=3)
        all_results.append({
            "text": text,
            "type": etype,
            "record_id": item.get("record_id", ""),
            "results": [r.to_dict() for r in results],
            "top_match": results[0].to_dict() if results else None,
        })
        if delay > 0 and i < len(terms) - 1:
            time.sleep(delay)
    return all_results
