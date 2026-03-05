"""
Enrichment routes: GND search, GND batch lookup, Wikidata SPARQL.

Router prefix: /api
"""
from __future__ import annotations

try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError("pip install fastapi")

from kwb.api.deps import get_workspace
from kwb.enrich.gnd import gnd_search, gnd_batch_search

router = APIRouter()


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
    Batch GND enrichment for all unique entities in the current workspace.

    Matches are written back into entity_reviews and the workspace dictionary.
    """
    ws = get_workspace()
    unique = ws.unique_entities()
    if not unique:
        return JSONResponse({"error": "Erst NER ausfuehren"}, 400)

    limit = min(request.get("limit", 50), 200)
    terms = [
        {"text": e.text, "type": e.entity_type, "record_id": e.record_id}
        for e in unique[:limit]
    ]
    results = gnd_batch_search(terms, delay=0.15)
    matched = 0
    for gr in results:
        if gr.get("top_match"):
            tm = gr["top_match"]
            for i, e in enumerate(ws.entities):
                if e.text == gr["text"] and e.entity_type == gr["type"]:
                    ws.update_entity(i, {
                        "gnd_id": tm["gnd_id"],
                        "gnd_preferred": tm["preferred_name"],
                    })
            ws.add_to_dictionary([{
                "term": gr["text"], "gnd_id": tm["gnd_id"],
                "gnd_preferred": tm["preferred_name"],
                "category": gr["type"], "source": "gnd-api",
            }])
            matched += 1

    return {
        "total": len(terms), "matched": matched,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Wikidata Enrichment (F28)
# ---------------------------------------------------------------------------

@router.get("/api/wikidata/search")
async def wikidata_search_api(q: str = "", type: str = "", lang: str = "de", size: int = 5):
    """
    Live Wikidata entity lookup via SPARQL.

    Parameters:
        q:    Search term
        type: Entity type filter: PER, LOC, GPE, ORG or empty for all
        lang: Language for labels (default "de")
        size: Max results (default 5)
    """
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
    Batch Wikidata enrichment for all unique entities in the current workspace.

    Request body:
        limit: int   -- max entities to process (default 30, max 100)
        lang: str    -- language for labels (default "de")
    """
    ws = get_workspace()
    unique = ws.unique_entities()
    if not unique:
        return JSONResponse({"error": "Erst NER ausfuehren"}, 400)

    limit = min(request.get("limit", 30), 100)
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
            entry = ws.lookup(wr["text"])
            if entry:
                entry.wikidata_id = qid
                if not entry.gnd_id and tm.get("gnd_id"):
                    entry.gnd_id = tm["gnd_id"]
            else:
                ws.add_to_dictionary([{
                    "term": wr["text"],
                    "gnd_id": tm.get("gnd_id", ""),
                    "category": wr.get("type", ""),
                    "source": "wikidata",
                }])
                fresh = ws.lookup(wr["text"])
                if fresh:
                    fresh.wikidata_id = qid
            matched += 1

    return {
        "total": len(terms),
        "matched": matched,
        "results": results,
    }
