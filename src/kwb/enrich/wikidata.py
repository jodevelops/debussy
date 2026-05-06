"""
Wikidata Enrichment (F28) — SPARQL-basierte Normdaten-Anreicherung.

Sucht Wikidata-Entitäten für Personen, Orte und Organisationen via SPARQL.
Unterstützt offline-Betrieb: gibt [] zurück wenn kein Netzwerk verfügbar.

SPARQL Endpoint: https://query.wikidata.org/sparql

Sprache (CORE-ENH-06, Issue #136):
    Die Default-Sprache wird über die Umgebungsvariable DEBUSSY_WIKIDATA_LANG
    gesteuert (Default "de"). Aufrufer können `lang=` pro Aufruf überschreiben.
    Das SPARQL-Label-Service nutzt automatisch Fallback auf Englisch
    (`wikibase:language "{lang},en"`).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "Debussy/0.5 (GLAM curation tool; https://github.com/example/debussy)"

# Default language for SPARQL queries (CORE-ENH-06, Issue #136).
# Override via DEBUSSY_WIKIDATA_LANG env var or per-call `lang=` argument.
DEFAULT_LANG = os.environ.get("DEBUSSY_WIKIDATA_LANG", "de")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class WikidataResult:
    """One Wikidata entity match."""
    qid: str               # e.g. "Q64" (Berlin)
    label: str             # preferred label (de or en)
    description: str = ""  # short description
    aliases: list[str] = field(default_factory=list)
    gnd_id: str = ""       # GND ID if linked (P227)
    type_labels: list[str] = field(default_factory=list)
    score: float = 1.0

    @property
    def uri(self) -> str:
        return f"https://www.wikidata.org/wiki/{self.qid}" if self.qid else ""

    def to_dict(self) -> dict:
        return {
            "qid": self.qid,
            "label": self.label,
            "description": self.description,
            "aliases": self.aliases,
            "gnd_id": self.gnd_id,
            "type_labels": self.type_labels,
            "uri": self.uri,
            "score": self.score,
        }


# ---------------------------------------------------------------------------
# SPARQL queries by entity type
# ---------------------------------------------------------------------------

def _sparql_search_query(term: str, lang: str | None = None, limit: int = 5) -> str:
    """
    Full-text SPARQL query using wikibase:mwapi for entity search.

    Returns items with their label, description, GND ID (P227), and type.
    """
    if lang is None:
        lang = DEFAULT_LANG
    safe = term.replace('"', '\\"')
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?gnd ?typeLabel WHERE {{
  SERVICE wikibase:mwapi {{
    bd:serviceParam wikibase:api "EntitySearch" .
    bd:serviceParam wikibase:endpoint "www.wikidata.org" .
    bd:serviceParam mwapi:search "{safe}" .
    bd:serviceParam mwapi:language "{lang}" .
    bd:serviceParam mwapi:limit {limit * 2} .
    ?item wikibase:apiOutputItem mwapi:item .
  }}
  OPTIONAL {{ ?item wdt:P227 ?gnd . }}
  OPTIONAL {{
    ?item wdt:P31 ?type .
    ?type rdfs:label ?typeLabel .
    FILTER(LANG(?typeLabel) = "{lang}")
  }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "{lang},en" .
  }}
}}
LIMIT {limit}
"""


def _sparql_person_query(term: str, lang: str | None = None, limit: int = 5) -> str:
    """Search specifically for persons (Q5)."""
    if lang is None:
        lang = DEFAULT_LANG
    safe = term.replace('"', '\\"')
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?gnd ?birth ?death WHERE {{
  SERVICE wikibase:mwapi {{
    bd:serviceParam wikibase:api "EntitySearch" .
    bd:serviceParam wikibase:endpoint "www.wikidata.org" .
    bd:serviceParam mwapi:search "{safe}" .
    bd:serviceParam mwapi:language "{lang}" .
    bd:serviceParam mwapi:limit {limit * 2} .
    ?item wikibase:apiOutputItem mwapi:item .
  }}
  ?item wdt:P31 wd:Q5 .
  OPTIONAL {{ ?item wdt:P227 ?gnd . }}
  OPTIONAL {{ ?item wdt:P569 ?birth . }}
  OPTIONAL {{ ?item wdt:P570 ?death . }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "{lang},en" .
  }}
}}
LIMIT {limit}
"""


def _sparql_place_query(term: str, lang: str | None = None, limit: int = 5) -> str:
    """Search for geographic locations."""
    if lang is None:
        lang = DEFAULT_LANG
    safe = term.replace('"', '\\"')
    return f"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?gnd ?coord WHERE {{
  SERVICE wikibase:mwapi {{
    bd:serviceParam wikibase:api "EntitySearch" .
    bd:serviceParam wikibase:endpoint "www.wikidata.org" .
    bd:serviceParam mwapi:search "{safe}" .
    bd:serviceParam mwapi:language "{lang}" .
    bd:serviceParam mwapi:limit {limit * 2} .
    ?item wikibase:apiOutputItem mwapi:item .
  }}
  ?item wdt:P31/wdt:P279* wd:Q2221906 .
  OPTIONAL {{ ?item wdt:P227 ?gnd . }}
  OPTIONAL {{ ?item wdt:P625 ?coord . }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "{lang},en" .
  }}
}}
LIMIT {limit}
"""


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _sparql_get(query: str, timeout: int = 15) -> list[dict[str, Any]]:
    """
    Execute a SPARQL query against Wikidata and return bindings.

    Returns [] on network error (offline-safe).
    """
    params = f"query={quote(query)}&format=json"
    url = f"{SPARQL_ENDPOINT}?{params}"
    req = Request(url, headers={
        "Accept": "application/sparql-results+json",
        "User-Agent": USER_AGENT,
    })
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("results", {}).get("bindings", [])
    except URLError as e:
        logger.warning(f"Wikidata SPARQL unavailable: {e}")
        return []
    except Exception as e:
        logger.warning(f"Wikidata SPARQL error: {e}")
        return []


def _binding_val(binding: dict, key: str) -> str:
    """Extract a string value from a SPARQL result binding."""
    v = binding.get(key, {})
    return str(v.get("value", "")) if v else ""


# ---------------------------------------------------------------------------
# Public search functions
# ---------------------------------------------------------------------------

def wikidata_search(
    term: str,
    entity_type: str = "",
    lang: str | None = None,
    limit: int = 5,
    timeout: int = 15,
) -> list[WikidataResult]:
    """
    Search Wikidata for a term.

    Parameters
    ----------
    term:       Search term (e.g. "Goethe", "Berlin", "UNESCO")
    entity_type: "PER", "LOC", "GPE", "ORG" or "" for general
    lang:       Language for labels and type filter. If None, uses
                DEFAULT_LANG (controlled by DEBUSSY_WIKIDATA_LANG env var,
                falls back to "de"). The SPARQL ``wikibase:label`` service
                automatically falls back to English for missing labels.
    limit:      Maximum results
    timeout:    HTTP timeout in seconds

    Returns [] on any network error (offline-safe).
    """
    if lang is None:
        lang = DEFAULT_LANG
    if not term or not term.strip():
        return []

    if entity_type == "PER":
        query = _sparql_person_query(term, lang=lang, limit=limit)
    elif entity_type in ("LOC", "GPE"):
        query = _sparql_place_query(term, lang=lang, limit=limit)
    else:
        query = _sparql_search_query(term, lang=lang, limit=limit)

    bindings = _sparql_get(query, timeout=timeout)

    seen: set[str] = set()
    results: list[WikidataResult] = []
    for b in bindings:
        qid_full = _binding_val(b, "item")
        qid = qid_full.rsplit("/", 1)[-1] if "/" in qid_full else qid_full
        if not qid or qid in seen:
            continue
        seen.add(qid)
        results.append(WikidataResult(
            qid=qid,
            label=_binding_val(b, "itemLabel"),
            description=_binding_val(b, "itemDescription"),
            gnd_id=_binding_val(b, "gnd"),
            type_labels=[_binding_val(b, "typeLabel")] if b.get("typeLabel") else [],
            score=1.0,
        ))

    return results[:limit]


def wikidata_batch_search(
    terms: list[dict],
    lang: str | None = None,
    limit: int = 3,
    delay: float = 1.0,
) -> list[dict]:
    """
    Batch Wikidata search for a list of {text, type, record_id} dicts.

    Respects Wikidata's rate limit with delay between requests.
    Returns [] for each failed lookup (offline-safe).

    Use ``lang=`` to override the default language; if None, uses
    DEFAULT_LANG (controlled by DEBUSSY_WIKIDATA_LANG env var).
    """
    if lang is None:
        lang = DEFAULT_LANG
    output = []
    for i, item in enumerate(terms):
        text = item.get("text", "")
        etype = item.get("type", "")
        record_id = item.get("record_id", "")

        results = wikidata_search(text, entity_type=etype, lang=lang, limit=limit)
        top = results[0] if results else None
        output.append({
            "text": text,
            "type": etype,
            "record_id": record_id,
            "results": [r.to_dict() for r in results],
            "top_match": top.to_dict() if top else None,
        })

        if delay > 0 and i < len(terms) - 1:
            time.sleep(delay)

    return output
