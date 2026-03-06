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
