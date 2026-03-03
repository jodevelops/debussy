"""GLAM-specific prompt templates."""
from __future__ import annotations
from kwb.ai.provider import AIMessage

SYSTEM_METADATA_EXPERT_DE = """Du bist ein Experte fuer Metadaten in GLAM-Institutionen (Galerien, Bibliotheken, Archive, Museen). Du arbeitest mit Sammlungsdaten und kennst GND, Wikidata, LIDO, METS/MODS, Dublin Core und Iconclass.

Antworte IMMER als valides JSON. Kein Markdown, keine Erklaerungen ausserhalb des JSON."""

SYSTEM_METADATA_EXPERT_EN = """You are a metadata expert for GLAM institutions. ALWAYS respond as valid JSON."""

SYSTEM_VISION_EXPERT_DE = """Du bist ein Experte fuer die Beschreibung von Sammlungsobjekten. Antworte IMMER als valides JSON."""

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

def prompt_classify_subject(subject_text, context="", language="de"):
    system = SYSTEM_METADATA_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    cats = "\n".join(f'  - "{k}": {v}' for k, v in NER_CATEGORIES.items())
    user = f'Klassifiziere: "{subject_text}"\n{f"Kontext: {context}" if context else ""}\n\nKategorien:\n{cats}\n\nJSON: {{"input":"...","terms":[],"classifications":[{{"term":"...","category":"...","confidence":0.0,"reasoning":"..."}}],"unclassified":[]}}'
    return [AIMessage.system(system), AIMessage.user(user)]

def prompt_describe_image(additional_context="", language="de"):
    user = f'Beschreibe fuer Sammlungskatalog.{f" Kontext: {additional_context}" if additional_context else ""}\n\nJSON: {{"description_short":"...","description_long":"...","objects":[],"geography":{{}},"architecture":[],"people":{{}},"time_period_estimate":"...","photography":{{}},"text_visible":"...","confidence":0.0}}'
    return [AIMessage.system(SYSTEM_VISION_EXPERT_DE), AIMessage.user(user)]

def prompt_normalize_term(term, field_name="", language="de"):
    system = SYSTEM_METADATA_EXPERT_DE
    user = f'Normalisiere: "{term}"\n{f"Feld: {field_name}" if field_name else ""}\n\nJSON: {{"original":"...","normalized":"...","changes":[],"gnd_candidate":null,"confidence":0.0}}'
    return [AIMessage.system(system), AIMessage.user(user)]

def prompt_ocr_analysis(additional_context="", language="de"):
    user = f'Analysiere auf Text.{f" Kontext: {additional_context}" if additional_context else ""}\n\nJSON: {{"text_found":false,"text_type":"...","language":"...","transcription":"...","text_regions":[],"overall_confidence":0.0}}'
    return [AIMessage.system(SYSTEM_VISION_EXPERT_DE), AIMessage.user(user)]
