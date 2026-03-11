"""
Dictionary routes: typed dictionaries, export, build from data, NER→dict, OCR→dict.

Router prefix: /api/dictionary
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse, Response
except ImportError:
    raise ImportError("pip install fastapi")

from kwb.api.deps import get_workspace, get_datasets
from kwb.core.workspace import DictionaryEntry, DictionaryType

router = APIRouter()


@router.get("/api/dictionary")
async def list_dictionary(entity_type: str = ""):
    """List all dictionary entries, optionally filtered by entity_type."""
    ws = get_workspace()
    if entity_type:
        entries = ws.dictionary_by_type(entity_type)
    else:
        entries = list(ws.dictionary)
    return {
        "entries": [e.to_dict() for e in entries],
        "total": len(entries),
        "types": list({e.entity_type or "other" for e in ws.dictionary}),
    }


@router.get("/api/dictionary/types")
async def dictionary_types():
    """Return available dictionary types and entry counts."""
    ws = get_workspace()
    counts: dict[str, int] = {}
    for e in ws.dictionary:
        t = e.entity_type or "other"
        counts[t] = counts.get(t, 0) + 1
    types = [
        {"type": dt.value, "label": dt.label_de, "count": counts.get(dt.value, 0)}
        for dt in DictionaryType
    ]
    return {"types": types, "total": len(ws.dictionary)}


@router.get("/api/dictionary/export")
async def export_dictionary(entity_type: str = "", format: str = "json"):
    """Export dictionary as JSON file download."""
    ws = get_workspace()
    if entity_type:
        entries = ws.dictionary_by_type(entity_type)
        filename = f"dictionary_{entity_type}.json"
    else:
        entries = list(ws.dictionary)
        filename = "dictionary_all.json"

    data = json.dumps(
        [e.to_dict() for e in entries], ensure_ascii=False, indent=2,
    )
    return Response(
        content=data.encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/dictionary/export-typed")
async def export_typed_dictionaries():
    """Export all dictionaries grouped by type as a single JSON."""
    ws = get_workspace()
    typed = ws.export_typed_dictionaries()
    data = json.dumps(typed, ensure_ascii=False, indent=2)
    return Response(
        content=data.encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="dictionaries_typed.json"'},
    )


@router.get("/api/dictionary/export-target")
async def export_dictionary_target(entity_type: str = ""):
    """Export dictionary in the target JSON format for downstream systems.

    Target format per entry:
    {
        "id": "entry_id",
        "category": "person",
        "term_source": "Joh. Seb. Bach",
        "term_normalized": "Johann Sebastian Bach",
        "source": "ocr",
        "authority": {
            "wikidata_qid": "Q1339",
            "gnd_id": "11850529X",
            "geonames_id": null
        },
        "occurrences": [{"record_id": "rec_001"}]
    }
    """
    ws = get_workspace()
    if entity_type:
        entries = ws.dictionary_by_type(entity_type)
    else:
        entries = list(ws.dictionary)

    def _to_target(entry):
        return {
            "id": entry.entry_id,
            "category": entry.entity_type,
            "term_source": entry.term,
            "term_normalized": entry.term_normalized or entry.preferred_name or entry.term,
            "source": entry.term_source or entry.source,
            "authority": {
                "wikidata_qid": entry.wikidata_id or None,
                "gnd_id": entry.gnd_id or None,
                "geonames_id": entry.geonames_id or None,
            },
            "occurrences": [{"record_id": rid} for rid in entry.record_ids],
        }

    data = json.dumps(
        [_to_target(e) for e in entries], ensure_ascii=False, indent=2,
    )
    filename = f"dictionary_target_{entity_type}.json" if entity_type else "dictionary_target.json"
    return Response(
        content=data.encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/pipeline/status")
async def pipeline_status():
    """Return pipeline progress across all three review gates."""
    ws = get_workspace()

    # Phase 1: OCR
    ocr_stats = {"total": 0, "pending": 0, "accepted": 0, "rejected": 0}
    for r in ws.image_analyses:
        ocr_stats["total"] += 1
        ocr_stats[r.review_status.value] = ocr_stats.get(r.review_status.value, 0) + 1

    # Phase 2: NER
    ner_stats = {"total": 0, "pending": 0, "accepted": 0, "rejected": 0}
    for e in ws.entity_reviews:
        ner_stats["total"] += 1
        ner_stats[e.status.value] = ner_stats.get(e.status.value, 0) + 1

    # Phase 3: Authority
    auth_stats = {"total": 0, "pending": 0, "accepted": 0, "rejected": 0}
    for c in ws.authority_candidates:
        auth_stats["total"] += 1
        auth_stats[c.status.value] = auth_stats.get(c.status.value, 0) + 1

    # Dictionary
    dict_total = len(ws.dictionary)
    enriched = sum(1 for e in ws.dictionary if e.has_authority)
    dict_stats = {
        "total": dict_total,
        "enriched": enriched,
        "unenriched": dict_total - enriched,
    }

    return {
        "phase1_ocr": ocr_stats,
        "phase2_ner": ner_stats,
        "phase3_authority": auth_stats,
        "dictionary": dict_stats,
    }


@router.post("/api/dictionary/entry")
async def add_or_update_entry(request: dict):
    """Add or update a single dictionary entry."""
    ws = get_workspace()
    term = (request.get("term") or "").strip()
    if not term:
        return JSONResponse({"error": "Kein Begriff angegeben"}, 400)

    entry = ws.lookup(term)
    if entry:
        # Update existing
        for key in ("preferred_name", "entity_type", "gnd_id", "gnd_preferred",
                     "gnd_type", "gnd_uri", "wikidata_id", "geonames_id", "note",
                     "source"):
            if key in request:
                setattr(entry, key, request[key])
        if "alternatives" in request:
            entry.alternatives = request["alternatives"]
        if "record_ids" in request:
            entry.merge_record_ids(request["record_ids"])
        ws._touch()
        return {"ok": True, "updated": True, "entry": entry.to_dict()}

    # Create new
    entity_type = request.get("entity_type", "")
    new_entry = DictionaryEntry(
        term=term,
        entity_type=entity_type,
        preferred_name=request.get("preferred_name", ""),
        record_ids=request.get("record_ids", []),
        gnd_id=request.get("gnd_id", ""),
        gnd_preferred=request.get("gnd_preferred", ""),
        gnd_type=request.get("gnd_type", ""),
        gnd_uri=request.get("gnd_uri", ""),
        wikidata_id=request.get("wikidata_id", ""),
        geonames_id=request.get("geonames_id", ""),
        alternatives=request.get("alternatives", []),
        source=request.get("source", "manual"),
        note=request.get("note", ""),
    )
    ws.add_entry(new_entry)
    return {"ok": True, "updated": False, "entry": new_entry.to_dict()}


@router.delete("/api/dictionary/entry/{entry_id}")
async def delete_entry(entry_id: str):
    """Delete a dictionary entry by entry_id."""
    ws = get_workspace()
    for i, e in enumerate(ws._dictionary):
        if e.entry_id == entry_id:
            removed = ws._dictionary.pop(i)
            ws._touch()
            return {"ok": True, "removed": removed.to_dict()}
    return JSONResponse({"error": "Eintrag nicht gefunden"}, 404)


@router.post("/api/dictionary/enrich/{entry_id}")
async def enrich_entry(entry_id: str, request: dict):
    """Enrich a dictionary entry with normdaten (GND, Wikidata, GeoNames)."""
    ws = get_workspace()
    entry = ws.lookup_by_id(entry_id)
    if not entry:
        return JSONResponse({"error": "Eintrag nicht gefunden"}, 404)

    # Update authority data
    for key in ("gnd_id", "gnd_preferred", "gnd_type", "gnd_uri",
                "wikidata_id", "geonames_id"):
        if key in request and request[key]:
            setattr(entry, key, request[key])

    if "preferred_name" in request:
        entry.preferred_name = request["preferred_name"]
    if "alternatives" in request:
        for alt in request["alternatives"]:
            if alt not in entry.alternatives:
                entry.alternatives.append(alt)

    entry.source = request.get("source", entry.source)
    ws._touch()
    return {"ok": True, "entry": entry.to_dict()}


@router.post("/api/dictionary/build")
async def build_from_dataset(request: dict):
    """Build dictionary entries from a dataset's columns."""
    dsn = request.get("dataset", "")
    ds = get_datasets().get(dsn)
    if not ds:
        return JSONResponse({"error": "Datensatz nicht geladen"}, 400)
    df, profile = ds
    columns = request.get("columns", [])
    if not columns:
        return JSONResponse({"error": "Keine Spalten angegeben"}, 400)
    entity_type = request.get("entity_type", "")
    id_column = profile.id_column or (df.columns[0] if len(df.columns) > 0 else "")
    ws = get_workspace()
    added = ws.build_dictionary_from_dataframe(
        df, columns, entity_type=entity_type,
        id_column=id_column, source="ingest",
    )
    return {
        "added": added,
        "total": len(ws.dictionary),
        "dataset": dsn,
        "columns": columns,
    }


@router.post("/api/dictionary/from-ner")
async def ner_to_dictionary(request: dict):
    """Transfer accepted NER entities into the dictionary."""
    ws = get_workspace()
    entity_types = request.get("entity_types", [])
    status_filter = request.get("status", "accepted")
    source_label = request.get("source", "ner")

    entries_to_add: list[dict] = []
    for er in ws.entity_reviews:
        if status_filter and er.status.value != status_filter:
            continue
        if entity_types and er.entity_type not in entity_types:
            continue
        dict_type = DictionaryType.from_entity_type(er.entity_type).value
        entries_to_add.append({
            "term": er.text,
            "entity_type": dict_type,
            "record_id": er.record_id,
            "gnd_id": er.gnd_id,
            "gnd_preferred": er.gnd_preferred,
            "source": source_label,
        })

    added = ws.add_to_dictionary(entries_to_add)
    return {
        "added": added,
        "processed": len(entries_to_add),
        "total": len(ws.dictionary),
    }


@router.post("/api/dictionary/from-ocr")
async def ocr_to_dictionary(request: dict):
    """Run NER on accepted OCR text results and add entities to review queue.

    REVIEW GATE: Only OCR results with review_status == ACCEPTED are processed.
    Entities are added to entity_reviews (not directly to dictionary).
    Use POST /api/dictionary/from-ner to transfer accepted entities to dictionary.

    Set include_pending=true to also process pending OCR results (legacy mode).
    """
    ws = get_workspace()
    include_pending = request.get("include_pending", False)

    # Collect OCR texts — GATE: only accepted OCR results
    ocr_texts: list[dict] = []
    skipped_pending = 0
    for analysis in ws.image_analyses:
        if not analysis.result:
            continue
        if analysis.review_status.value == "accepted":
            pass  # always include accepted
        elif include_pending and analysis.review_status.value == "pending":
            pass  # include pending only in legacy mode
        else:
            if analysis.review_status.value == "pending":
                skipped_pending += 1
            continue

        text = (analysis.result.get("transcription") or
                analysis.result.get("text") or "")
        if not text.strip():
            continue
        ocr_texts.append({
            "text": text,
            "record_id": analysis.record_id or analysis.image_id,
            "column": f"[OCR] {analysis.filename}",
        })

    if not ocr_texts:
        msg = "Keine akzeptierten OCR-Ergebnisse vorhanden."
        if skipped_pending > 0:
            msg += (
                f" {skipped_pending} Ergebnisse warten auf Review."
                " Bitte zuerst OCR-Ergebnisse prüfen (Tab Bilder)."
            )
        else:
            msg += " Bitte zuerst OCR durchführen."
        return JSONResponse({"error": msg}, 400)

    # Run NER on OCR texts
    entity_types = request.get("entity_types", ["PER", "ORG", "LOC", "GPE"])
    model = request.get("model", "")

    from kwb.api.deps import get_provider
    from kwb.analyze.ner import ner_llm

    provider = get_provider(model)
    llm_entities, batch = ner_llm(ocr_texts, provider, model=model or None)

    # Filter by requested entity types
    entities_added = []
    for entity in llm_entities:
        if entity_types and entity.entity_type.value not in entity_types:
            continue
        entities_added.append({
            "text": entity.text,
            "type": entity.entity_type.value,
            "confidence": entity.confidence,
            "record_id": entity.record_id,
        })

    # Add to entity_reviews for review (NOT directly to dictionary)
    ws.add_entities([
        {
            "text": e.text,
            "type": e.entity_type.value,
            "confidence": e.confidence,
            "reasoning": e.reasoning,
            "source": "ocr",
            "record_id": e.record_id,
        }
        for e in llm_entities
    ])

    return {
        "ocr_texts_processed": len(ocr_texts),
        "skipped_pending": skipped_pending,
        "entities_found": len(llm_entities),
        "entities_filtered": len(entities_added),
        "entities_in_review": len(ws.entity_reviews),
        "entities": entities_added[:200],
    }
