"""GLAM-specific prompt templates."""
from __future__ import annotations

from kwb.ai.provider import AIMessage

SYSTEM_METADATA_EXPERT_DE = """Du bist ein Experte fuer Metadaten in GLAM-Institutionen (Galerien, Bibliotheken, Archive, Museen). Du arbeitest mit Sammlungsdaten und kennst GND, Wikidata, LIDO, METS/MODS, Dublin Core und Iconclass.

Antworte IMMER als valides JSON. Kein Markdown, keine Erklaerungen ausserhalb des JSON."""
SYSTEM_METADATA_EXPERT_EN = """You are a metadata expert for GLAM institutions. ALWAYS respond as valid JSON."""
SYSTEM_VISION_EXPERT_DE = """Du bist ein Experte fuer die Beschreibung von Sammlungsobjekten. Antworte IMMER als valides JSON."""

PROMPT_VERSIONS = {
    "image_description": "1.0.0",
    "alt_text": "1.0.0",
    "person_face_visibility": "1.0.0",
    "ocr_transcription_quality": "1.0.0",
    "entity_extraction_normdata": "1.0.0",
}

NER_CATEGORIES = {
    "PER": "Personen (Namen, Titel, Berufsbezeichnungen)",
    "ORG": "Organisationen (Institutionen, Firmen, Vereine)",
    "LOC": "Orte/Geografie (Berge, Fluesse, Taeler, Landschaften)",
    "GPE": "Geo-politische Einheiten (Laender, Staedte, Kantone)",
    "FAC": "Bauwerke/Einrichtungen (Gebaeude, Bruecken, Denkmaeler)",
    "EVT": "Ereignisse (historische Ereignisse, Ausstellungen)",
    "WRK": "Werke/Publikationen (Buecher, Karten, Kunstwerke)",
    "DAT": "Datums-/Zeitangaben",
    "ETH": "Ethnien/Kulturgruppen",
    "CON": "Konzepte/Sachthemen (allgemeine Sachbegriffe, Themen)",
}

CLASSIFICATION_CATEGORIES = {
    "NE_Person": "Personen", "NE_Ethnic_Group": "Ethnische Gruppen",
    "NE_Place": "Orte", "NE_Named_Building": "Benannte Gebaeude",
    "NE_Publication": "Publikationen",
    "Physical_Geography": "Physische Geographie",
    "Architecture_Infrastructure": "Architektur und Infrastruktur",
    "Human_Geography": "Humangeographie",
    "Nature_Agriculture": "Natur und Landwirtschaft",
    "Science_Cartography": "Wissenschaft und Kartographie",
    "Religion_Belief": "Religion und Glaube",
    "Art_Culture_History": "Kunst, Kultur und Geschichte",
}


def _ctx_line(additional_context: str) -> str:
    return f"Kontext: {additional_context}\n" if additional_context else ""


def _quality_rules(label: str) -> str:
    return (
        f"Qualitaetskriterien fuer {label}:\n"
        "- Pflichtfelder duerfen niemals fehlen; nutze null oder [] falls unbekannt.\n"
        "- confidence muss als Zahl zwischen 0.0 und 1.0 ausgegeben werden.\n"
        "- uncertain muss true sein, wenn Unsicherheit, schlechte Bild-/Textqualitaet oder Mehrdeutigkeit vorliegt.\n"
        "- uncertainty_note ist Pflicht wenn uncertain=true, sonst leerer String.\n"
        "- Keine Halluzinationen: lieber als unsicher markieren als raten."
    )


def prompt_classify_subject(subject_text, context="", language="de"):
    system = SYSTEM_METADATA_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    cats = "\n".join(f'  - "{k}": {v}' for k, v in NER_CATEGORIES.items())
    user = f'Klassifiziere: "{subject_text}"\n{f"Kontext: {context}" if context else ""}\n\nKategorien:\n{cats}\n\nJSON: {{"input":"...","terms":[],"classifications":[{{"term":"...","category":"...","confidence":0.0,"reasoning":"..."}}],"unclassified":[]}}'
    return [AIMessage.system(system), AIMessage.user(user)]


def prompt_image_description(additional_context="", language="de"):
    system = SYSTEM_VISION_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    user = (
        "Aufgabe: Erstelle Bildbeschreibung und Alt-Text fuer einen Sammlungskatalog.\n"
        + _ctx_line(additional_context)
        + _quality_rules("Bildbeschreibung")
        + "\n\nJSON-Schema:\n"
        + "{\n"
        + '  "prompt_name": "image_description",\n'
        + '  "prompt_version": "1.0.0",\n'
        + '  "description_short": "...",\n'
        + '  "description_long": "...",\n'
        + '  "alt_text": "...",\n'
        + '  "objects": [{"label": "...", "count": 1, "confidence": 0.0}],\n'
        + '  "setting": {"location_type": "...", "time_period_estimate": "..."},\n'
        + '  "confidence": 0.0,\n'
        + '  "uncertain": false,\n'
        + '  "uncertainty_note": ""\n'
        + "}"
    )
    return [AIMessage.system(system), AIMessage.user(user)]


def prompt_person_face_visibility(additional_context="", language="de"):
    system = SYSTEM_VISION_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    user = (
        "Aufgabe: Bewerte Sichtbarkeit von Personen und Gesichtern im Bild.\n"
        + _ctx_line(additional_context)
        + _quality_rules("Personen-/Gesichtssichtbarkeit")
        + "\n\nJSON-Schema:\n"
        + "{\n"
        + '  "prompt_name": "person_face_visibility",\n'
        + '  "prompt_version": "1.0.0",\n'
        + '  "persons_detected": 0,\n'
        + '  "faces_visible": 0,\n'
        + '  "visibility_rating": "none|partial|clear",\n'
        + '  "subjects": [{"subject_id":"p1","is_person":true,"face_visible":false,"occlusion":"...","confidence":0.0}],\n'
        + '  "privacy_risk": "low|medium|high",\n'
        + '  "confidence": 0.0,\n'
        + '  "uncertain": false,\n'
        + '  "uncertainty_note": ""\n'
        + "}"
    )
    return [AIMessage.system(system), AIMessage.user(user)]


def prompt_ocr_transcription_quality(additional_context="", language="de"):
    system = SYSTEM_VISION_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    user = (
        "Aufgabe: Fuehre OCR/HTR durch und bewerte die Transkriptionsqualitaet.\n"
        + _ctx_line(additional_context)
        + _quality_rules("OCR/Transkription")
        + "\n\nJSON-Schema:\n"
        + "{\n"
        + '  "prompt_name": "ocr_transcription_quality",\n'
        + '  "prompt_version": "1.0.0",\n'
        + '  "text_found": false,\n'
        + '  "text_type": "printed|handwritten|mixed|unknown",\n'
        + '  "script_type": "latin|kurrent|fraktur|mixed|unknown",\n'
        + '  "language": "de|en|fr|it|la|unknown",\n'
        + '  "transcription": "...",\n'
        + '  "quality": {"legibility": "poor|medium|good", "completeness": 0.0, "noise_level": 0.0},\n'
        + '  "text_regions": [{"bbox":[0,0,0,0], "line_estimate":0, "confidence":0.0}],\n'
        + '  "overall_confidence": 0.0,\n'
        + '  "uncertain": false,\n'
        + '  "uncertainty_note": ""\n'
        + "}"
    )
    return [AIMessage.system(system), AIMessage.user(user)]


def prompt_entity_extraction_normdata(source_text, context="", language="de"):
    system = SYSTEM_METADATA_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    cats = ", ".join(NER_CATEGORIES.keys())
    context_line = f"Kontext: {context}\n" if context else ""
    user = (
        f'Aufgabe: Extrahiere Entitaeten fuer Normdatenabgleich aus: "{source_text}"\n'
        + context_line
        + f"Erlaubte Typen: {cats}\n"
        + _quality_rules("Entitaeten-Extraktion")
        + "\n\nJSON-Schema:\n"
        + "{\n"
        + '  "prompt_name": "entity_extraction_normdata",\n'
        + '  "prompt_version": "1.0.0",\n'
        + '  "input": "...",\n'
        + '  "entities": [\n'
        + '    {"text":"...","type":"PER","confidence":0.0,"context_snippet":"...","candidate_ids":[{"authority":"gnd|wikidata","id":"...","label":"...","confidence":0.0}],"uncertain":false,"uncertainty_note":""}\n'
        + "  ],\n"
        + '  "unmatched_terms": ["..."],\n'
        + '  "confidence": 0.0,\n'
        + '  "uncertain": false,\n'
        + '  "uncertainty_note": ""\n'
        + "}"
    )
    return [AIMessage.system(system), AIMessage.user(user)]


def prompt_describe_image(additional_context="", language="de"):
    return prompt_image_description(additional_context=additional_context, language=language)


def prompt_normalize_term(term, field_name="", language="de"):
    system = SYSTEM_METADATA_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    user = f'Normalisiere: "{term}"\n{f"Feld: {field_name}" if field_name else ""}\n\nJSON: {{"original":"...","normalized":"...","changes":[],"gnd_candidate":null,"confidence":0.0}}'
    return [AIMessage.system(system), AIMessage.user(user)]


def prompt_ocr_analysis(additional_context="", language="de"):
    return prompt_ocr_transcription_quality(additional_context=additional_context, language=language)


# ---------------------------------------------------------------------------
# LLM-gestützte Qualitätsprüfung (Phase 2)
# ---------------------------------------------------------------------------

_SYSTEM_QUALITY_EXPERT_DE = (
    "Du bist ein Experte fuer die Qualitaetspruefung von Metadaten in GLAM-Institutionen "
    "(Galerien, Bibliotheken, Archive, Museen). Du kennst GND, Dublin Core, LIDO und METS/MODS. "
    "Antworte IMMER als valides JSON. Kein Markdown, keine Erklaerungen ausserhalb des JSON."
)


def prompt_cell_quality_check(
    field_name: str,
    field_semantics: str,
    value: str,
    record_context: dict,
    dataset_profile: dict,
    language: str = "de",
) -> list:
    """
    Field-sensitive cell-level quality check prompt.

    Checks whether *value* is semantically appropriate for *field_name*,
    using record context and dataset profile for grounding.
    """
    system = _SYSTEM_QUALITY_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    semantics_line = f"Erwartete Feldsemantik: {field_semantics}\n" if field_semantics else ""
    ctx_lines = ""
    if record_context:
        ctx_pairs = "; ".join(f"{k}: {v}" for k, v in list(record_context.items())[:8])
        ctx_lines = f"Andere Felder desselben Datensatzes: {ctx_pairs}\n"
    ds_cols = ", ".join(dataset_profile.get("columns", [])[:20])
    ds_line = (
        f"Datensatzprofil: Quelle={dataset_profile.get('source_name','')}, "
        f"Zeilen={dataset_profile.get('row_count','')}, Felder={ds_cols}\n"
    )
    user = (
        f"Aufgabe: Pruefe semantische Qualitaet des Zellwerts im Kontext seines Feldes.\n\n"
        f"Feld: {field_name}\n"
        + semantics_line
        + f"Zellwert: {value}\n"
        + ctx_lines
        + ds_line
        + "\nJSON-Schema (genau dieses Format, alle Felder Pflicht):\n"
        + "{\n"
        + '  "value": "...",\n'
        + '  "field": "...",\n'
        + '  "issue_type": "likely_correct|semantic_misplacement|ambiguous|generic|'
        + 'encoding_artifact|review_required",\n'
        + '  "severity": "critical|warning|info",\n'
        + '  "confidence": 0.0,\n'
        + '  "reasoning": "...",\n'
        + '  "evidence": {},\n'
        + '  "suggested_target_field": null,\n'
        + '  "suggested_action": "accept|move_or_review|flag_for_review|correct",\n'
        + '  "review_required": false\n'
        + "}"
    )
    return [AIMessage.system(system), AIMessage.user(user)]


def prompt_column_quality_check(
    field_name: str,
    field_semantics: str,
    sample_values: list,
    non_empty_count: int,
    total_count: int,
    language: str = "de",
) -> list:
    """
    Column-level field-purity assessment prompt.

    Evaluates how well the sample values match the expected field semantics
    and reports a purity score with dominant issue types.
    """
    system = _SYSTEM_QUALITY_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    semantics_line = f"Erwartete Feldsemantik: {field_semantics}\n" if field_semantics else ""
    vals_repr = ", ".join(f'"{v}"' for v in sample_values[:30])
    user = (
        f"Aufgabe: Bewerte die semantische Feldqualitaet (Feldreinheit) der Spalte.\n\n"
        f"Spalte: {field_name}\n"
        + semantics_line
        + f"Nicht-leere Werte: {non_empty_count} von {total_count}\n"
        + f"Stichprobe (bis 30 Werte): [{vals_repr}]\n"
        + "\nJSON-Schema (genau dieses Format, alle Felder Pflicht):\n"
        + "{\n"
        + '  "column": "...",\n'
        + '  "field_purity_score": 0.0,\n'
        + '  "dominant_issue_types": [],\n'
        + '  "typical_problems": [],\n'
        + '  "affected_value_examples": [],\n'
        + '  "suggested_action": "...",\n'
        + '  "confidence": 0.0,\n'
        + '  "reasoning": "...",\n'
        + '  "review_required": false\n'
        + "}"
    )
    return [AIMessage.system(system), AIMessage.user(user)]


def prompt_record_quality_check(
    record_id: str,
    fields: dict,
    language: str = "de",
) -> list:
    """
    Record-level cross-field coherence check prompt.

    Detects contradictions and semantic inconsistencies between fields
    within a single record.
    """
    system = _SYSTEM_QUALITY_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    fields_repr = "\n".join(f"  {k}: {v}" for k, v in fields.items())
    user = (
        f"Aufgabe: Pruefe Kohaerenz und Widersprueche innerhalb eines Metadaten-Datensatzes.\n\n"
        f"Datensatz-ID: {record_id}\n"
        f"Felder:\n{fields_repr}\n"
        + "\nJSON-Schema (genau dieses Format, alle Felder Pflicht):\n"
        + "{\n"
        + '  "record_id": "...",\n'
        + '  "severity": "critical|warning|info|ok",\n'
        + '  "conflicts": [\n'
        + '    {"fields": [], "description": "...", "confidence": 0.0}\n'
        + "  ],\n"
        + '  "overall_confidence": 0.0,\n'
        + '  "reasoning": "...",\n'
        + '  "review_required": false\n'
        + "}"
    )
    return [AIMessage.system(system), AIMessage.user(user)]


def prompt_dataset_quality_summary(
    source_name: str,
    row_count: int,
    column_count: int,
    analyzed_columns: list,
    issue_summary: dict,
    language: str = "de",
) -> list:
    """
    Dataset-level quality synthesis prompt.

    Aggregates cell/column findings into dominant error families,
    issue clusters, and actionable work-package candidates.
    """
    system = _SYSTEM_QUALITY_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    cols_repr = ", ".join(analyzed_columns[:20])
    total_findings = issue_summary.get("total_findings", 0)
    issue_counts = issue_summary.get("issue_type_counts", {})
    purity_scores = issue_summary.get("column_purity_scores", {})
    counts_repr = "; ".join(f"{k}={v}" for k, v in issue_counts.items())
    purity_repr = "; ".join(f"{k}={v:.0f}" for k, v in purity_scores.items())
    user = (
        f"Aufgabe: Fasse die KI-Qualitaetsbefunde des gesamten Datensatzes zusammen.\n\n"
        f"Datensatz: {source_name} ({row_count} Zeilen, {column_count} Spalten)\n"
        f"Analysierte Spalten: {cols_repr}\n"
        f"Gesamtbefunde: {total_findings}\n"
        f"Befundtypen: {counts_repr}\n"
        f"Feldreinheit (Spalte=Score): {purity_repr}\n"
        + "\nJSON-Schema (genau dieses Format, alle Felder Pflicht):\n"
        + "{\n"
        + '  "dominant_error_families": [],\n'
        + '  "at_risk_columns": [],\n'
        + '  "issue_clusters": [\n'
        + '    {"label":"...","affected_columns":[],"count":0,"severity":"warning","suggested_action":"..."}\n'
        + "  ],\n"
        + '  "work_package_candidates": [\n'
        + '    {"title":"...","description":"...","priority":"warning","affected_columns":[],'
        + '"estimated_records":0,"action_type":"review"}\n'
        + "  ],\n"
        + '  "risk_summary": "...",\n'
        + '  "confidence": 0.0\n'
        + "}"
    )
    return [AIMessage.system(system), AIMessage.user(user)]
