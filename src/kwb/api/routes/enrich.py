"""
Enrichment routes: GND search, GND batch lookup, (future: Wikidata, GeoNames).

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
        return JSONResponse({"error": "Erst NER ausführen"}, 400)

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
