"""
GLAM-specific prompt templates for Debussy.

Each function returns a list of AIMessages ready to send to any provider.
Prompts are versioned, language-aware, and produce structured JSON output.
"""
from __future__ import annotations
from kwb.ai.provider import AIMessage

# ---------------------------------------------------------------------------
# System prompts (editable in UI)
# ---------------------------------------------------------------------------

SYSTEM_METADATA_EXPERT_DE = """Du bist ein Experte fuer Metadaten in GLAM-Institutionen \
(Galerien, Bibliotheken, Archive, Museen). Du arbeitest mit Sammlungsdaten \
und kennst GND, Wikidata, LIDO, METS/MODS, Dublin Core und Iconclass.

Antworte IMMER als valides JSON. Kein Markdown, keine Erklaerungen ausserhalb des JSON."""

SYSTEM_METADATA_EXPERT_EN = """You are a metadata expert for GLAM institutions \
(Galleries, Libraries, Archives, Museums). You work with collection data \
and are familiar with GND, Wikidata, LIDO, METS/MODS, Dublin Core, and Iconclass.

ALWAYS respond as valid JSON. No markdown, no explanations outside the JSON."""

SYSTEM_VISION_EXPERT_DE = """Du bist ein Experte fuer die Beschreibung von Sammlungsobjekten \
in GLAM-Institutionen. Du beschreibst Bilder praezise und fachlich korrekt, \
mit besonderem Augenmerk auf geographische, architektonische und kulturelle Merkmale.

Antworte IMMER als valides JSON. Kein Markdown, keine Erklaerungen ausserhalb des JSON."""

# ---------------------------------------------------------------------------
# Generic NER categories (domain-agnostic, standard ontology)
# ---------------------------------------------------------------------------

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

# Legacy: geography-specific categories (for backward compatibility with GIUB data)
CLASSIFICATION_CATEGORIES = {
    "NE_Person": "Personen (Namen, Titel, Berufsbezeichnungen)",
    "NE_Ethnic_Group": "Ethnische Gruppen und Voelker",
    "NE_Place": "Orte und geographische Bezeichnungen",
    "NE_Named_Building": "Benannte Gebaeude und Bauwerke",
    "NE_Publication": "Publikationen und Schriften",
    "Physical_Geography": "Physische Geographie (Gelaendeformen, Gewaesser, Klima)",
    "Architecture_Infrastructure": "Architektur und Infrastruktur",
    "Human_Geography": "Humangeographie (Siedlungen, Verkehr, Wirtschaft)",
    "Nature_Agriculture": "Natur und Landwirtschaft",
    "Science_Cartography": "Wissenschaft und Kartographie",
    "Religion_Belief": "Religion und Glaube",
    "Art_Culture_History": "Kunst, Kultur und Geschichte",
}


# ---------------------------------------------------------------------------
# Prompt functions
# ---------------------------------------------------------------------------

def prompt_classify_subject(
    subject_text: str, context: str = "", language: str = "de",
) -> list[AIMessage]:
    """Classify a subject string into NER categories."""
    system = SYSTEM_METADATA_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    categories_str = "\n".join(f'  - "{k}": {v}' for k, v in NER_CATEGORIES.items())

    user_content = f"""Klassifiziere den folgenden Schlagwort-String in eine oder mehrere Kategorien.

Schlagwort: "{subject_text}"
{f'Kontext: {context}' if context else ''}

Verfuegbare Kategorien:
{categories_str}

Antworte als JSON:
{{
  "input": "<der originale String>",
  "terms": ["<einzelne Terme, aufgetrennt>"],
  "classifications": [
    {{
      "term": "<einzelner Term>",
      "category": "<Kategorie-Key>",
      "confidence": <0.0-1.0>,
      "reasoning": "<kurze Begruendung>"
    }}
  ],
  "unclassified": ["<Terme, die in keine Kategorie passen>"]
}}"""
    return [AIMessage.system(system), AIMessage.user(user_content)]


def prompt_describe_image(
    additional_context: str = "", language: str = "de",
) -> list[AIMessage]:
    """Generate a structured description of an image."""
    user_text = f"""Beschreibe dieses Bild fuer einen Sammlungskatalog.
{f'Kontext: {additional_context}' if additional_context else ''}

Antworte als JSON:
{{
  "description_short": "<1 Satz, praegnant>",
  "description_long": "<2-4 Saetze, detailliert>",
  "objects": ["<erkannte Objekte>"],
  "geography": {{
    "landscape_type": "<z.B. Berglandschaft, Kueste, Wueste>",
    "vegetation": "<z.B. Nadelwald, Steppe>",
    "climate_indicators": "<z.B. Schnee, tropisch>"
  }},
  "architecture": ["<erkannte Bauwerke/Typen>"],
  "people": {{"count": <Anzahl oder 0>, "activities": ["<Aktivitaeten>"]}},
  "time_period_estimate": "<geschaetzte Epoche>",
  "photography": {{"type": "<Schwarzweiss/Farbe>", "perspective": "<Panorama/Nahaufnahme>"}},
  "text_visible": "<sichtbarer Text oder leer>",
  "confidence": <0.0-1.0>
}}"""
    return [AIMessage.system(SYSTEM_VISION_EXPERT_DE), AIMessage.user(user_text)]


def prompt_normalize_term(
    term: str, field_name: str = "", language: str = "de",
) -> list[AIMessage]:
    """Normalize a metadata term (fix typos, standardize form)."""
    system = SYSTEM_METADATA_EXPERT_DE if language == "de" else SYSTEM_METADATA_EXPERT_EN
    user_content = f"""Normalisiere den folgenden Metadaten-Term.
{f'Feld: {field_name}' if field_name else ''}

Term: "{term}"

Antworte als JSON:
{{
  "original": "<originaler Term>",
  "normalized": "<normalisierter Term>",
  "changes": ["<Liste der Aenderungen>"],
  "gnd_candidate": "<moeglicher GND-Vorzugsname, oder null>",
  "confidence": <0.0-1.0>
}}"""
    return [AIMessage.system(system), AIMessage.user(user_content)]


def prompt_ocr_analysis(
    additional_context: str = "", language: str = "de",
) -> list[AIMessage]:
    """Analyze an image for text content (OCR/HTR)."""
    user_text = f"""Analysiere dieses Bild auf sichtbaren Text (gedruckt oder handschriftlich).
{f'Kontext: {additional_context}' if additional_context else ''}

Antworte als JSON:
{{
  "text_found": true/false,
  "text_type": "<gedruckt/handschriftlich/gemischt/keiner>",
  "language": "<erkannte Sprache(n)>",
  "transcription": "<vollstaendige Transkription>",
  "text_regions": [
    {{
      "location": "<z.B. oben-links, Bildmitte>",
      "content": "<Text>",
      "confidence": <0.0-1.0>
    }}
  ],
  "overall_confidence": <0.0-1.0>
}}"""
    return [AIMessage.system(SYSTEM_VISION_EXPERT_DE), AIMessage.user(user_text)]
