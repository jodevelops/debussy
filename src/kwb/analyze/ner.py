"""
Named Entity Recognition — generic, domain-agnostic NER.

Uses SpaCy (if available) for baseline NER, then optionally enhances
with LLM for GLAM-specific refinement and confidence scoring.

Entity types follow standard ontologies (not geography-specific):
  PER  — Person (names, titles)
  ORG  — Organization (institutions, companies)
  LOC  — Location (places, regions, geographic features)
  GPE  — Geo-Political Entity (countries, cities, states)
  FAC  — Facility (named buildings, monuments, bridges)
  EVT  — Event (historical events, exhibitions)
  WRK  — Work (publications, artworks, maps)
  DAT  — Date/Time expressions
  ETH  — Ethnic/Cultural group
  CON  — Concept/Subject (generic subjects, topics)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

from kwb.ai.provider import AIMessage, AIProvider
from kwb.ai.batch import process_batch, BatchReport, CompletionSummary

logger = logging.getLogger(__name__)


class EntityType(str, Enum):
    """Standard NER entity types, GLAM-extended."""
    PER = "PER"
    ORG = "ORG"
    LOC = "LOC"
    GPE = "GPE"
    FAC = "FAC"
    EVT = "EVT"
    WRK = "WRK"
    DAT = "DAT"
    ETH = "ETH"
    CON = "CON"
    TOP = "TOP"

    @property
    def label_de(self) -> str:
        return {
            "PER": "Person", "ORG": "Organisation", "LOC": "Ort/Geografie",
            "GPE": "Geo-politische Einheit", "FAC": "Bauwerk/Einrichtung",
            "EVT": "Ereignis", "WRK": "Werk/Publikation",
            "DAT": "Datum/Zeit", "ETH": "Ethnie/Kulturgruppe",
            "CON": "Konzept/Thema", "TOP": "Thema/Schlagwort",
        }[self.value]


@dataclass
class Entity:
    """A single recognized entity with provenance."""
    text: str
    entity_type: EntityType
    confidence: float = 0.0
    reasoning: str = ""
    source: str = ""         # "spacy", "llm", "hybrid", "manual"
    record_id: str = ""
    column: str = ""
    gnd_id: str | None = None
    gnd_preferred: str | None = None
    wikidata_id: str | None = None
    normalized: str | None = None
    reviewed: bool = False

    @property
    def dedup_key(self) -> str:
        """Case-insensitive deduplication key: (text.lower().strip(), entity_type)."""
        return f"{self.text.strip().lower()}||{self.entity_type.value}"


@dataclass
class NERResult:
    """Result of NER on one dataset."""
    entities: list[Entity] = field(default_factory=list)
    batch_report: BatchReport | None = None
    completion_summary: CompletionSummary | None = None

    @property
    def by_type(self) -> dict[EntityType, list[Entity]]:
        result: dict[EntityType, list[Entity]] = {}
        for e in self.entities:
            result.setdefault(e.entity_type, []).append(e)
        return result

    @property
    def unique_entities(self) -> dict[str, "Entity"]:
        """Deduplicated by dedup_key (case-insensitive text + type), keeping highest confidence."""
        best: dict[str, "Entity"] = {}
        for e in self.entities:
            key = e.dedup_key
            if key not in best or e.confidence > best[key].confidence:
                best[key] = e
        return best

    def to_dict_list(self, deduplicated: bool = True) -> list[dict]:
        """Serialize for JSON/API.

        Args:
            deduplicated: If True (default), returns only unique entities per dedup_key.
                          If False, returns all entities including duplicates.
        """
        source = list(self.unique_entities.values()) if deduplicated else self.entities
        return [
            {
                "text": e.text, "type": e.entity_type.value,
                "type_label": e.entity_type.label_de,
                "confidence": round(e.confidence, 3),
                "reasoning": e.reasoning, "source": e.source,
                "record_id": e.record_id, "column": e.column,
                "gnd_id": e.gnd_id, "gnd_preferred": e.gnd_preferred,
                "wikidata_id": e.wikidata_id,
                "normalized": e.normalized, "reviewed": e.reviewed,
            }
            for e in source
        ]


# ---------------------------------------------------------------------------
# SpaCy-based NER (optional dependency)
# ---------------------------------------------------------------------------

_spacy_nlp = None

def _get_spacy(model: str = "de_core_news_lg"):
    global _spacy_nlp
    if _spacy_nlp is not None:
        return _spacy_nlp
    try:
        import spacy
        for m in [model, "de_core_news_md", "de_core_news_sm"]:
            try:
                _spacy_nlp = spacy.load(m)
                logger.info(f"SpaCy model loaded: {m}")
                return _spacy_nlp
            except OSError:
                continue
        logger.warning("No SpaCy German model found.")
        return None
    except ImportError:
        logger.info("SpaCy not installed.")
        return None


_SPACY_TYPE_MAP = {
    "PER": EntityType.PER, "PERSON": EntityType.PER,
    "ORG": EntityType.ORG,
    "LOC": EntityType.LOC,
    "GPE": EntityType.GPE,
    "FAC": EntityType.FAC,
    "EVENT": EntityType.EVT,
    "WORK_OF_ART": EntityType.WRK,
    "DATE": EntityType.DAT,
    "NORP": EntityType.ETH,
    "MISC": EntityType.CON,
}


def ner_spacy(
    texts: list[dict[str, str]],
    model: str = "de_core_news_lg",
) -> list[Entity]:
    nlp = _get_spacy(model)
    if nlp is None:
        return []
    entities = []
    for item in texts:
        doc = nlp(item["text"])
        for ent in doc.ents:
            etype = _SPACY_TYPE_MAP.get(ent.label_, EntityType.CON)
            entities.append(Entity(
                text=ent.text, entity_type=etype, confidence=0.6,
                source="spacy",
                record_id=item.get("record_id", ""),
                column=item.get("column", ""),
            ))
    return entities


# ---------------------------------------------------------------------------
# LLM-based NER
# ---------------------------------------------------------------------------

SYSTEM_NER = """Du bist ein Experte fuer Named Entity Recognition (NER) in Metadaten
von GLAM-Institutionen (Galerien, Bibliotheken, Archive, Museen).

Erkenne und klassifiziere alle benannten Entitaeten in den gegebenen Texten.
Verwende diese Kategorien:
  PER  — Person (Namen, Titel, Funktionen)
  ORG  — Organisation (Institutionen, Firmen, Vereine)
  LOC  — Ort (geographische Merkmale: Berge, Fluesse, Taeler)
  GPE  — Geo-politische Einheit (Laender, Staedte, Kantone)
  FAC  — Bauwerk/Einrichtung (Gebaeude, Bruecken, Denkmaeler)
  EVT  — Ereignis (historische Ereignisse, Ausstellungen)
  WRK  — Werk (Publikationen, Kunstwerke, Karten)
  DAT  — Datum/Zeitangabe
  ETH  — Ethnie/Kulturgruppe
  CON  — Konzept/Thema (allgemeine Sachbegriffe)
  TOP  — Thema/Schlagwort (uebergeordnete Themen, generische Schlagwoerter)

Antworte IMMER als valides JSON. Kein Markdown."""


def ner_llm(
    texts: list[dict[str, str]],
    provider: AIProvider,
    model: str | None = None,
    system_prompt: str = "",
) -> tuple[list[Entity], BatchReport]:
    def _make_prompt(item: dict[str, Any]) -> list[AIMessage]:
        return [
            AIMessage.system(system_prompt or SYSTEM_NER),
            AIMessage.user(
                f'Analysiere diesen Text und extrahiere alle Named Entities:\n\n'
                f'Text: "{item["text"]}"\n'
                f'Feld: {item.get("column", "")}\n'
                f'Record: {item.get("record_id", "")}\n\n'
                f'Antworte als JSON:\n'
                f'{{"entities": [{{"text": "...", "type": "PER|ORG|LOC|GPE|FAC|EVT|WRK|DAT|ETH|CON|TOP", '
                f'"confidence": 0.0-1.0, "reasoning": "..."}}]}}'
            ),
        ]

    batch = process_batch(
        provider=provider, items=texts,
        prompt_fn=_make_prompt, id_field="record_id", model=model,
    )

    entities = []
    for result in batch.results:
        if result.parsed and "entities" in result.parsed:
            for ent_data in result.parsed["entities"]:
                try:
                    etype = EntityType(ent_data.get("type", "CON"))
                except ValueError:
                    etype = EntityType.CON
                entities.append(Entity(
                    text=ent_data.get("text", ""),
                    entity_type=etype,
                    confidence=float(ent_data.get("confidence", 0.5)),
                    reasoning=ent_data.get("reasoning", ""),
                    source="llm",
                    record_id=result.record_id,
                ))
    return entities, batch


# ---------------------------------------------------------------------------
# Hybrid NER (SpaCy + LLM merge) — FIXED deduplication
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Hybrid NER (SpaCy + LLM merge) — FIXED deduplication
# ---------------------------------------------------------------------------


def _merge_entity_lists(
    spacy_entities: list["Entity"],
    llm_entities: list["Entity"],
) -> list["Entity"]:
    """
    Merge two entity lists (SpaCy + LLM), deduplicating by dedup_key.

    Rules:
    - Entities unique to one source keep their original source tag.
    - Entities found by both sources get source="hybrid".
    - On confidence ties, LLM wins.
    - Higher confidence always wins regardless of source.

    Returns a flat list (order: spacy-only, then hybrid/llm-only items).
    """
    spacy_map: dict[str, "Entity"] = {}
    for e in spacy_entities:
        k = e.dedup_key
        if k not in spacy_map or e.confidence > spacy_map[k].confidence:
            spacy_map[k] = e

    llm_map: dict[str, "Entity"] = {}
    for e in llm_entities:
        k = e.dedup_key
        if k not in llm_map or e.confidence > llm_map[k].confidence:
            llm_map[k] = e

    merged: dict[str, "Entity"] = dict(spacy_map)
    for k, llm_ent in llm_map.items():
        if k in merged:
            spacy_ent = merged[k]
            # LLM wins on tie or higher confidence
            if llm_ent.confidence >= spacy_ent.confidence:
                winner = llm_ent
            else:
                winner = spacy_ent
            winner.source = "hybrid"
            merged[k] = winner
        else:
            merged[k] = llm_ent

    return list(merged.values())


def ner_hybrid(
    df: pd.DataFrame,
    columns: list[str],
    provider: AIProvider | None = None,
    id_column: str | None = None,
    sample_size: int | None = None,
    model: str | None = None,
    system_prompt: str = "",
    use_spacy: bool = True,
    use_llm: bool = True,
    entity_types: list[str] | None = None,
) -> NERResult:
    """
    Run hybrid NER on selected columns of a DataFrame.

    Combines SpaCy (fast, baseline) with LLM (accurate, slow).
    Deduplicates: entities found by both get source='hybrid'.
    LLM result wins on confidence ties.
    """
    working = df.copy()
    if sample_size and sample_size < len(working):
        working = working.sample(n=sample_size, random_state=42)

    texts = []
    for _, row in working.iterrows():
        rid = str(row.get(id_column, "")) if id_column else ""
        for col in columns:
            if col in row and pd.notna(row[col]) and str(row[col]).strip():
                texts.append({
                    "record_id": rid,
                    "text": str(row[col]).strip(),
                    "column": col,
                })

    result = NERResult()
    batch = None

    # Collect per-source, keyed by (record_id, column, text, type)
    spacy_map: dict[str, Entity] = {}
    llm_map: dict[str, Entity] = {}

    if use_spacy:
        for e in ner_spacy(texts):
            k = f"{e.record_id}||{e.column}||{e.text}||{e.entity_type.value}"
            if k not in spacy_map or e.confidence > spacy_map[k].confidence:
                spacy_map[k] = e

    if use_llm and provider:
        llm_ents, batch = ner_llm(texts, provider, model=model, system_prompt=system_prompt)
        for e in llm_ents:
            k = f"{e.record_id}||{e.column}||{e.text}||{e.entity_type.value}"
            if k not in llm_map or e.confidence > llm_map[k].confidence:
                llm_map[k] = e
        result.batch_report = batch

        # Calculate completion summary from batch report
        if batch:
            parse_failed = len(batch.parse_failures)
            llm_failed = batch.failed
            succeeded_with_entities = len(llm_ents)
            # Items with non-null parsed but no entities
            empty_results = sum(1 for r in batch.results
                              if r.success and r.parsed is not None
                              and r.record_id not in {e.record_id for e in llm_ents})

            result.completion_summary = CompletionSummary(
                total_records=batch.total,
                succeeded=succeeded_with_entities,
                llm_failed=llm_failed,
                parse_failed=parse_failed,
                empty_result=empty_results
            )

    # Merge: start with SpaCy, upgrade overlaps to hybrid/llm
    merged: dict[str, Entity] = dict(spacy_map)
    for k, llm_ent in llm_map.items():
        if k in merged:
            # Both found — use LLM result, mark as hybrid
            winner = llm_ent if llm_ent.confidence >= merged[k].confidence else merged[k]
            winner.source = "hybrid"
            merged[k] = winner
        else:
            merged[k] = llm_ent

    result.entities = list(merged.values())

    # Feature 9: Filter by requested entity types
    if entity_types:
        allowed = set(entity_types)
        result.entities = [e for e in result.entities if e.entity_type.value in allowed]

    return result


# ---------------------------------------------------------------------------
# Full-dataset scan (problematic terms)
# ---------------------------------------------------------------------------

def scan_problematic_terms(
    df: pd.DataFrame,
    provider: AIProvider,
    id_column: str | None = None,
    sample_size: int = 20,
    model: str | None = None,
    system_prompt: str = "",
) -> tuple[list[dict], BatchReport]:
    SYSTEM_SCAN = system_prompt or """Du bist ein Experte fuer Metadatenqualitaet in GLAM-Institutionen.
Analysiere diese Metadaten-Werte und identifiziere potentiell problematische Begriffe:
- Veraltete oder koloniale Terminologie
- Diskriminierende oder stigmatisierende Begriffe
- Historisch belastete Bezeichnungen
- Nicht mehr zeitgemaesse ethnische/geographische Bezeichnungen

Antworte IMMER als valides JSON."""

    str_cols = [c for c in df.columns if df[c].dtype.kind in ('O', 'U') or str(df[c].dtype) == "string"]
    working = df.sample(n=min(sample_size, len(df)), random_state=42) if sample_size < len(df) else df

    items = []
    for _, row in working.iterrows():
        rid = str(row.get(id_column, "")) if id_column else ""
        all_vals = "; ".join(
            str(row[c]).strip()
            for c in str_cols
            if pd.notna(row[c]) and str(row[c]).strip()
        )
        if all_vals:
            items.append({"record_id": rid, "text": all_vals[:500]})

    def _make_prompt(item: dict) -> list[AIMessage]:
        return [
            AIMessage.system(SYSTEM_SCAN),
            AIMessage.user(
                f'Analysiere diese Metadaten auf problematische Begriffe:\n\n'
                f'Record: {item["record_id"]}\n'
                f'Werte: "{item["text"]}"\n\n'
                f'Antworte als JSON:\n'
                f'{{"problematic_terms": [{{"term": "...", "reason": "...", '
                f'"severity": "high|medium|low", "suggestion": "..."}}], '
                f'"clean": true/false}}'
            ),
        ]

    batch = process_batch(provider, items, _make_prompt, model=model)
    issues = []
    for r in batch.results:
        if r.parsed and r.parsed.get("problematic_terms"):
            for t in r.parsed["problematic_terms"]:
                t["record_id"] = r.record_id
                issues.append(t)
    return issues, batch
