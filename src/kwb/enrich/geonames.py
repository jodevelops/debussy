"""
GeoNames enrichment client.

Queries the GeoNames JSON API (api.geonames.org/searchJSON) for geographic
entities. Requires a free GeoNames username (env var KWB_GEONAMES_USERNAME).
"""
from __future__ import annotations

import json
import logging
import time as _time
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GEONAMES_BASE = "http://api.geonames.org/searchJSON"


@dataclass
class GeoNamesResult:
    """One GeoNames search result."""
    geonames_id: str
    name: str
    country: str = ""
    country_code: str = ""
    feature_class: str = ""
    feature_code: str = ""
    lat: float = 0.0
    lng: float = 0.0
    population: int = 0

    @property
    def uri(self) -> str:
        return f"https://www.geonames.org/{self.geonames_id}" if self.geonames_id else ""

    def to_dict(self) -> dict:
        return {
            "geonames_id": self.geonames_id,
            "name": self.name,
            "country": self.country,
            "country_code": self.country_code,
            "feature_class": self.feature_class,
            "feature_code": self.feature_code,
            "lat": self.lat,
            "lng": self.lng,
            "population": self.population,
            "uri": self.uri,
        }


def geonames_search(
    term: str,
    username: str = "demo",
    max_rows: int = 5,
    lang: str = "de",
    feature_class: str = "",
    timeout: int = 10,
) -> list[GeoNamesResult]:
    """Search GeoNames for a geographic term.

    Returns up to max_rows results. Returns [] on empty query or network error.
    """
    if not term or not term.strip():
        return []
    if not username:
        logger.warning("GeoNames username not configured")
        return []

    params = {
        "q": term,
        "maxRows": str(min(max_rows, 20)),
        "username": username,
        "lang": lang,
        "type": "json",
    }
    if feature_class:
        params["featureClass"] = feature_class

    url = f"{GEONAMES_BASE}?{urlencode(params)}"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"GeoNames API unavailable for '{term}': {e}")
        return []

    results = []
    for item in data.get("geonames", []):
        results.append(GeoNamesResult(
            geonames_id=str(item.get("geonameId", "")),
            name=item.get("name", ""),
            country=item.get("countryName", ""),
            country_code=item.get("countryCode", ""),
            feature_class=item.get("fcl", ""),
            feature_code=item.get("fcode", ""),
            lat=float(item.get("lat", 0) or 0),
            lng=float(item.get("lng", 0) or 0),
            population=int(item.get("population", 0) or 0),
        ))

    return results


def geonames_batch_search(
    terms: list[dict],
    username: str = "demo",
    delay: float = 1.0,
    max_rows: int = 5,
) -> list[dict]:
    """Batch GeoNames search for a list of {text, type, record_id} dicts.

    Returns a list of {text, record_id, results, top_match} dicts.
    Rate-limits requests with a configurable delay.
    """
    if not terms:
        return []

    output = []
    for i, item in enumerate(terms):
        text = item.get("text", "")
        record_id = item.get("record_id", "")

        try:
            results = geonames_search(text, username=username, max_rows=max_rows)
        except Exception as e:
            logger.warning(f"GeoNames batch search failed for '{text}': {e}")
            results = []

        top = results[0] if results else None
        output.append({
            "text": text,
            "record_id": record_id,
            "results": [r.to_dict() for r in results],
            "top_match": top.to_dict() if top else None,
        })

        if delay > 0 and i < len(terms) - 1:
            _time.sleep(delay)

    return output
