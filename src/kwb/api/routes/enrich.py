"""
Enrichment routes: GND search, GND batch, Wikidata SPARQL, GeoNames,
and authority candidate review.

Router prefix: /api
"""
from __future__ import annotations

import logging

try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError("pip install fastapi")

from kwb.api.deps import get_workspace, get_config
from kwb.enrich.gnd import gnd_search, gnd_batch_search
from kwb.core.workspace import AuthorityCandidate, ReviewStatus

logger = logging.getLogger(__name__)

router = APIRouter()


def _validate_limit(request: dict, default: int, max_val: int) -> tuple[int | None, JSONResponse | None]:
    """
    Validate and normalize limit parameter from request.
    Returns (limit, error_response) where error_response is None if valid.
    """
    limit = request.get("limit", default)
    if not isinstance(limit, int) or limit < 0:
        return None, JSONResponse(
            {"error": f"limit muss eine nicht-negative ganze Zahl sein (max {max_val})"},
            400
        )
    return min(limit, max_val), None


@router.get("/api/gnd/search")
async def gnd_search_api(q: str = "", type: str = "", size: int = 5):
    """Live GND term lookup via lobid.org (no AI)."""
    if not q:
        return {"results": []}
    results = gnd_search(q, entity_type=type, size=size)
    return {"results": [r.to_dict() for r in results]}


@router.post("/api/gnd/batch")
async def gnd_batch_api(request: dict):
    """
    Batch GND enrichment — creates AuthorityCandidates for review.

    Matches are NOT written directly into the dictionary. Instead they
    become AuthorityCandidate records with status=pending.
    Use POST /api/authority/commit to write accepted candidates to dictionary.
    """
    ws = get_workspace()
    unique = ws.unique_entities()
    if not unique:
        return JSONResponse({"error": "Erst NER ausfuehren"}, 400)

    limit, err = _validate_limit(request, 50, 200)
    if err:
        return err
    terms = [
        {"text": e.text, "type": e.entity_type, "record_id": e.record_id}
        for e in unique[:limit]
    ]
    results = gnd_batch_search(terms, delay=0.15)
    matched = 0
    for gr in results:
        if gr.get("top_match"):
            tm = gr["top_match"]
            # Ensure dictionary entry exists for the term
            entry = ws.lookup(gr["text"])
            if not entry:
                ws.add_to_dictionary([{
                    "term": gr["text"],
                    "category": gr["type"],
                    "source": "gnd-api",
                }])
                entry = ws.lookup(gr["text"])

            if entry:
                ws.add_authority_candidate(AuthorityCandidate(
                    entry_id=entry.entry_id,
                    source="gnd",
                    authority_id=tm["gnd_id"],
                    preferred_name=tm["preferred_name"],
                    authority_type=tm.get("gnd_type", ""),
                    uri=f"https://d-nb.info/gnd/{tm['gnd_id']}",
                    score=tm.get("confidence", 0.8),
                ))

            # Still update entity_reviews for backward compat
            for i, e in enumerate(ws.entities):
                if e.text == gr["text"] and e.entity_type == gr["type"]:
                    ws.update_entity(i, {
                        "gnd_id": tm["gnd_id"],
                        "gnd_preferred": tm["preferred_name"],
                    })
            matched += 1

    return {
        "total": len(terms), "matched": matched,
        "candidates_created": matched,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Wikidata Enrichment (F28)
# ---------------------------------------------------------------------------

@router.get("/api/wikidata/search")
async def wikidata_search_api(
    q: str = "", type: str = "", lang: str = "de", size: int = 5,
):
    """Live Wikidata entity lookup via SPARQL."""
    if not q:
        return {"results": []}
    try:
        from kwb.enrich.wikidata import wikidata_search
        results = wikidata_search(q, entity_type=type, lang=lang, limit=min(size, 10))
        return {"results": [r.to_dict() for r in results]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@router.post("/api/wikidata/batch")
async def wikidata_batch_api(request: dict):
    """
    Batch Wikidata enrichment — creates AuthorityCandidates for review.

    Request body:
        limit: int   -- max entities to process (default 30, max 100)
        lang: str    -- language for labels (default "de")
    """
    ws = get_workspace()
    unique = ws.unique_entities()
    if not unique:
        return JSONResponse({"error": "Erst NER ausfuehren"}, 400)

    limit, err = _validate_limit(request, 30, 100)
    if err:
        return err
    lang = request.get("lang", "de")

    terms = [
        {"text": e.text, "type": e.entity_type, "record_id": e.record_id}
        for e in unique[:limit]
    ]

    try:
        from kwb.enrich.wikidata import wikidata_batch_search
        results = wikidata_batch_search(terms, lang=lang, limit=3, delay=1.0)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

    matched = 0
    for wr in results:
        if wr.get("top_match"):
            tm = wr["top_match"]
            qid = tm.get("qid", "")
            # Ensure dictionary entry exists
            entry = ws.lookup(wr["text"])
            if not entry:
                ws.add_to_dictionary([{
                    "term": wr["text"],
                    "category": wr.get("type", ""),
                    "source": "wikidata",
                }])
                entry = ws.lookup(wr["text"])

            if entry:
                type_labels = tm.get("type_labels", [])
                authority_type = type_labels[0] if type_labels else ""
                ws.add_authority_candidate(AuthorityCandidate(
                    entry_id=entry.entry_id,
                    source="wikidata",
                    authority_id=qid,
                    preferred_name=tm.get("label", ""),
                    authority_type=authority_type,
                    uri=tm.get("uri", ""),
                    score=float(tm.get("score", 0.8)),
                    extra={"gnd_id": tm.get("gnd_id", "")},
                ))
            matched += 1

    return {
        "total": len(terms),
        "matched": matched,
        "candidates_created": matched,
        "results": results,
    }


# ---------------------------------------------------------------------------
# GeoNames Enrichment
# ---------------------------------------------------------------------------

@router.get("/api/geonames/search")
async def geonames_search_api(q: str = "", size: int = 5):
    """Live GeoNames term lookup."""
    if not q:
        return {"results": []}
    try:
        from kwb.enrich.geonames import geonames_search
        cfg = get_config()
        username = cfg.geonames_username or "demo"
        results = geonames_search(q, username=username, max_rows=size)
        return {"results": [r.to_dict() for r in results]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@router.post("/api/geonames/batch")
async def geonames_batch_api(request: dict):
    """
    Batch GeoNames enrichment — creates AuthorityCandidates for review.

    Request body:
        limit: int   -- max entities to process (default 30, max 100)
        entity_types: list[str] -- filter by NER types (default ["LOC", "GPE"])
    """
    ws = get_workspace()
    unique = ws.unique_entities()
    if not unique:
        return JSONResponse({"error": "Erst NER ausfuehren"}, 400)

    limit, err = _validate_limit(request, 30, 100)
    if err:
        return err
    entity_types = request.get("entity_types", ["LOC", "GPE"])

    filtered = [e for e in unique if e.entity_type in entity_types] if entity_types else unique
    terms = [
        {"text": e.text, "type": e.entity_type, "record_id": e.record_id}
        for e in filtered[:limit]
    ]

    try:
        from kwb.enrich.geonames import geonames_batch_search
        cfg = get_config()
        username = cfg.geonames_username
        if not username:
            return JSONResponse({
                "error": "GeoNames API not configured. Set geonames_username in config. "
                         "Demo account has rate limits (2000 req/day) unsuitable for production."
            }, 503)
        results = geonames_batch_search(terms, username=username, delay=1.0)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

    matched = 0
    candidates_created = 0
    for gr in results:
        # Create candidates for all results, not just top_match, with position-based scoring
        all_results = gr.get("results", [])
        for pos, result_dict in enumerate(all_results):
            entry = ws.lookup(gr["text"])
            if not entry:
                ws.add_to_dictionary([{
                    "term": gr["text"],
                    "category": "place",
                    "source": "geonames",
                }])
                entry = ws.lookup(gr["text"])

            if entry:
                # Position-based scoring: 1.0 for top, decreases with position
                position_score = 1.0 if pos == 0 else max(0.3, 1.0 - pos * 0.15)

                # Use feature_code (e.g. "PPLC", "ADM1") if present, fallback to feature_class
                geo_type = result_dict.get("feature_code") or result_dict.get("feature_class") or "PlaceOrGeographicName"
                ws.add_authority_candidate(AuthorityCandidate(
                    entry_id=entry.entry_id,
                    source="geonames",
                    authority_id=result_dict["geonames_id"],
                    preferred_name=result_dict["name"],
                    authority_type=geo_type,
                    uri=result_dict.get("uri", ""),
                    score=position_score,
                    extra={
                        "country": result_dict.get("country", ""),
                        "country_code": result_dict.get("country_code", ""),
                        "lat": result_dict.get("lat", 0),
                        "lng": result_dict.get("lng", 0),
                        "feature_class": result_dict.get("feature_class", ""),
                        "population": result_dict.get("population", 0),
                    },
                ))
                candidates_created += 1
        if all_results:
            matched += 1

    return {
        "total": len(terms),
        "matched": matched,
        "candidates_created": candidates_created,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Authority Candidate Review
# ---------------------------------------------------------------------------

@router.get("/api/authority/candidates")
async def authority_candidates_list(
    entry_id: str = "", status: str = "", source: str = "",
):
    """List authority candidates, optionally filtered."""
    ws = get_workspace()
    candidates = ws.authority_candidates

    if entry_id:
        candidates = [c for c in candidates if c.entry_id == entry_id]
    if status:
        candidates = [c for c in candidates if c.status.value == status]
    if source:
        candidates = [c for c in candidates if c.source == source]

    return {
        "candidates": [c.to_dict() for c in candidates],
        "total": len(candidates),
        "stats": ws.authority_review_stats(),
    }


@router.post("/api/authority/candidates/{candidate_id}/review")
async def authority_candidate_review(candidate_id: str, request: dict):
    """Accept or reject a single authority candidate."""
    ws = get_workspace()
    target = None
    for c in ws.authority_candidates:
        if c.candidate_id == candidate_id:
            target = c
            break
    if not target:
        return JSONResponse({"error": "Kandidat nicht gefunden"}, 404)

    new_status = request.get("status", "")
    note = request.get("note", "")

    if new_status == "accepted":
        target.accept(note=note)
    elif new_status == "rejected":
        target.reject(note=note)
    else:
        return JSONResponse({"error": "Status muss 'accepted' oder 'rejected' sein"}, 400)

    return {"ok": True, "candidate": target.to_dict()}


@router.post("/api/authority/candidates/batch-review")
async def authority_candidates_batch_review(request: dict):
    """Batch accept/reject authority candidates."""
    ws = get_workspace()
    candidate_ids = request.get("candidate_ids", [])
    new_status = request.get("status", "")
    note = request.get("note", "")

    if new_status not in ("accepted", "rejected"):
        return JSONResponse({"error": "Status muss 'accepted' oder 'rejected' sein"}, 400)

    updated = 0
    id_set = set(candidate_ids)
    for c in ws.authority_candidates:
        if c.candidate_id in id_set:
            if new_status == "accepted":
                c.accept(note=note)
            else:
                c.reject(note=note)
            updated += 1

    return {"updated": updated, "status": new_status}


@router.post("/api/authority/commit")
async def authority_commit(request: dict = {}):
    """Write all accepted authority candidates into their DictionaryEntry fields."""
    ws = get_workspace()
    committed = 0

    for candidate in ws.authority_candidates:
        if candidate.status != ReviewStatus.ACCEPTED:
            continue

        entry = ws.lookup_by_id(candidate.entry_id)
        if not entry:
            continue

        if candidate.source == "gnd":
            entry.gnd_id = candidate.authority_id
            entry.gnd_preferred = candidate.preferred_name
            entry.gnd_type = candidate.authority_type
            entry.gnd_uri = candidate.uri
        elif candidate.source == "wikidata":
            entry.wikidata_id = candidate.authority_id
            entry.wikidata_preferred = candidate.preferred_name
            entry.wikidata_type = candidate.authority_type
            entry.wikidata_uri = candidate.uri
            if not entry.gnd_id and candidate.extra.get("gnd_id"):
                entry.gnd_id = candidate.extra["gnd_id"]
        elif candidate.source == "geonames":
            entry.geonames_id = candidate.authority_id
            entry.geonames_preferred = candidate.preferred_name
            entry.geonames_type = candidate.authority_type
            entry.geonames_uri = candidate.uri

        if candidate.preferred_name and not entry.preferred_name:
            entry.preferred_name = candidate.preferred_name

        committed += 1

    ws._touch()
    return {
        "committed": committed,
        "dictionary_total": len(ws.dictionary),
        "stats": ws.authority_review_stats(),
    }
