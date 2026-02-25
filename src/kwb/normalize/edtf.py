"""
EDTF — Extended Date/Time Format normalization.

Converts heterogeneous date strings from GLAM metadata into
LOC EDTF (Library of Congress Extended Date/Time Format).

Spec: https://www.loc.gov/standards/datetime/
Supports: Level 0, Level 1, Level 2

Common GLAM date patterns handled:
  "1920"          → "1920"
  "ca. 1920"      → "1920~"
  "um 1920"       → "1920~"
  "vor 1920"      → "../1920"
  "nach 1920"     → "1920/.."
  "1920-1930"     → "1920/1930"
  "1920er"        → "192X"
  "19. Jh."       → "18XX"  (century = n-1)
  "Anfang 19. Jh."→ "18XX"
  "1920-03"       → "1920-03"
  "1920-03-15"    → "1920-03-15"
  "[1920]"        → "1920?"
  "1920?"         → "1920?"
  "o.D."          → ""  (undated)
  ""              → ""
"""
from __future__ import annotations

import re
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from kwb.ai.provider import AIMessage, AIProvider
from kwb.ai.batch import process_batch, BatchReport, _try_parse_json

logger = logging.getLogger(__name__)


@dataclass
class EDTFResult:
    """Result of converting a single date string."""
    original: str
    edtf: str
    confidence: float = 1.0
    method: str = "rule"   # "rule" or "llm"
    note: str = ""
    valid: bool = True


@dataclass
class EDTFReport:
    """Summary of EDTF conversion for a batch."""
    results: list[EDTFResult] = field(default_factory=list)
    total: int = 0
    converted: int = 0
    failed: int = 0
    undated: int = 0

    @property
    def success_rate(self) -> float:
        return self.converted / self.total if self.total > 0 else 0.0


# ---------------------------------------------------------------------------
# Rule-based patterns (fast, no AI needed)
# ---------------------------------------------------------------------------

# German approximate markers
_APPROX = re.compile(
    r'^(ca\.?|circa|um|ungefähr|approx\.?|etwa)\s*', re.IGNORECASE
)

# "vor YYYY" → "../YYYY"
_BEFORE = re.compile(
    r'^(vor|before|bis|ante)\s+(\d{4})', re.IGNORECASE
)

# "nach YYYY" → "YYYY/.."
_AFTER = re.compile(
    r'^(nach|after|ab|seit|post)\s+(\d{4})', re.IGNORECASE
)

# Range: "YYYY-YYYY" or "YYYY–YYYY" or "YYYY bis YYYY"
_RANGE = re.compile(
    r'^(\d{4})\s*[-–—/]\s*(\d{4})$'
)
_RANGE_TEXT = re.compile(
    r'^(\d{4})\s+(bis|to|und|and)\s+(\d{4})$', re.IGNORECASE
)

# Decade: "1920er" "1920er Jahre" "1920s"
_DECADE = re.compile(
    r'^(\d{3})0\s*-?(er|er\s+Jahre|s)$', re.IGNORECASE
)

# Century: "19. Jh." "19. Jahrhundert" "XIX. Jahrhundert"
_CENTURY_ARABIC = re.compile(
    r'^(?:Anfang|Mitte|Ende|Beginn)?\s*(\d{1,2})\.\s*(Jh\.?|Jahrhundert|century)', re.IGNORECASE
)

# Uncertain: "[YYYY]" or "YYYY?"
_UNCERTAIN_BRACKET = re.compile(r'^\[(\d{4})\]$')
_UNCERTAIN_QUESTION = re.compile(r'^(\d{4})\?$')

# ISO-ish: YYYY, YYYY-MM, YYYY-MM-DD
_ISO_YEAR = re.compile(r'^(\d{4})$')
_ISO_MONTH = re.compile(r'^(\d{4})-(\d{2})$')
_ISO_DAY = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')

# Undated markers
_UNDATED = re.compile(
    r'^(o\.?\s*D\.?|undatiert|undated|s\.?\s*d\.?|ohne Datum|keine Angabe|n\.?\s*d\.?|unbekannt)$',
    re.IGNORECASE
)

# "Anfang/Mitte/Ende" + range
_POSITION_CENTURY = re.compile(
    r'^(Anfang|Beginn|Mitte|Ende|Erstes Drittel|Zweites Drittel|Letztes Drittel)\s+(\d{1,2})\.\s*(Jh\.?|Jahrhundert)',
    re.IGNORECASE
)


def normalize_edtf(date_str: str) -> EDTFResult:
    """
    Convert a single date string to EDTF using rule-based patterns.

    Returns an EDTFResult with the conversion details.
    """
    original = date_str.strip()
    if not original:
        return EDTFResult(original="", edtf="", confidence=1.0, note="leer")

    text = original.strip()

    # Undated
    if _UNDATED.match(text):
        return EDTFResult(original=original, edtf="", confidence=1.0,
                         note="undatiert", method="rule")

    # Remove approximate markers, remember for EDTF qualifier
    approx = False
    m = _APPROX.match(text)
    if m:
        approx = True
        text = text[m.end():].strip()

    # Uncertain: [YYYY]
    m = _UNCERTAIN_BRACKET.match(text)
    if m:
        return EDTFResult(original=original, edtf=f"{m.group(1)}?",
                         confidence=0.95, method="rule", note="unsicher (Klammern)")

    # Uncertain: YYYY?
    m = _UNCERTAIN_QUESTION.match(text)
    if m:
        return EDTFResult(original=original, edtf=f"{m.group(1)}?",
                         confidence=0.95, method="rule", note="unsicher (Fragezeichen)")

    # Before
    m = _BEFORE.match(text)
    if m:
        year = m.group(2)
        edtf = f"../{year}"
        if approx:
            edtf = f"../{year}~"
        return EDTFResult(original=original, edtf=edtf,
                         confidence=0.9, method="rule", note=f"vor {year}")

    # After
    m = _AFTER.match(text)
    if m:
        year = m.group(2)
        edtf = f"{year}/.."
        if approx:
            edtf = f"{year}~/.."
        return EDTFResult(original=original, edtf=edtf,
                         confidence=0.9, method="rule", note=f"nach {year}")

    # Range: YYYY-YYYY
    m = _RANGE.match(text) or _RANGE_TEXT.match(text)
    if m:
        groups = m.groups()
        y1, y2 = groups[0], groups[-1]
        qualifier = "~" if approx else ""
        return EDTFResult(original=original, edtf=f"{y1}{qualifier}/{y2}{qualifier}",
                         confidence=0.95, method="rule", note=f"Zeitraum {y1}–{y2}")

    # Decade: 1920er
    m = _DECADE.match(text)
    if m:
        decade = m.group(1)
        qualifier = "~" if approx else ""
        return EDTFResult(original=original, edtf=f"{decade}X{qualifier}",
                         confidence=0.9, method="rule", note=f"{decade}0er Jahre")

    # Century with position: "Anfang 19. Jh."
    m = _POSITION_CENTURY.match(text)
    if m:
        position = m.group(1).lower()
        century = int(m.group(2)) - 1  # "19. Jh." = 1800s
        qualifier = "~" if approx else ""
        return EDTFResult(original=original, edtf=f"{century:02d}XX{qualifier}",
                         confidence=0.7, method="rule",
                         note=f"{position.title()} {m.group(2)}. Jahrhundert")

    # Century: "19. Jh."
    m = _CENTURY_ARABIC.match(text)
    if m:
        century = int(m.group(1)) - 1  # "19. Jh." = 18XX
        qualifier = "~" if approx else ""
        return EDTFResult(original=original, edtf=f"{century:02d}XX{qualifier}",
                         confidence=0.85, method="rule",
                         note=f"{m.group(1)}. Jahrhundert")

    # ISO day
    m = _ISO_DAY.match(text)
    if m:
        qualifier = "~" if approx else ""
        return EDTFResult(original=original, edtf=f"{text}{qualifier}",
                         confidence=1.0, method="rule")

    # ISO month
    m = _ISO_MONTH.match(text)
    if m:
        qualifier = "~" if approx else ""
        return EDTFResult(original=original, edtf=f"{text}{qualifier}",
                         confidence=1.0, method="rule")

    # Plain year
    m = _ISO_YEAR.match(text)
    if m:
        qualifier = "~" if approx else ""
        return EDTFResult(original=original, edtf=f"{text}{qualifier}",
                         confidence=1.0, method="rule")

    # No rule matched → needs LLM or manual
    return EDTFResult(original=original, edtf="", confidence=0.0,
                     method="rule", valid=False,
                     note="Kein Muster erkannt — LLM oder manuell")


# ---------------------------------------------------------------------------
# Batch conversion (rule-based)
# ---------------------------------------------------------------------------

def normalize_edtf_batch(
    date_strings: list[dict[str, str]],
) -> EDTFReport:
    """
    Convert a batch of date strings.

    Args:
        date_strings: [{"record_id": "...", "date": "..."}]
    """
    report = EDTFReport(total=len(date_strings))

    for item in date_strings:
        result = normalize_edtf(item.get("date", ""))
        result_with_id = EDTFResult(
            original=result.original, edtf=result.edtf,
            confidence=result.confidence, method=result.method,
            note=result.note, valid=result.valid,
        )
        report.results.append(result_with_id)

        if not result.original or result.note == "undatiert":
            report.undated += 1
        elif result.valid and result.edtf:
            report.converted += 1
        else:
            report.failed += 1

    return report


# ---------------------------------------------------------------------------
# LLM-assisted conversion (for dates that rules can't handle)
# ---------------------------------------------------------------------------

SYSTEM_EDTF = """Du bist ein Experte fuer Datierungen in GLAM-Metadaten.
Konvertiere Datumsangaben in EDTF-Format (LOC Extended Date/Time Format).

EDTF-Regeln:
- Einfaches Jahr: "1920"
- Approximation: "1920~" (ca./um/ungefaehr)
- Unsicher: "1920?" (fraglich)
- Zeitraum: "1920/1930"
- Vor: "../1920"  Nach: "1920/.."
- Dekade: "192X"
- Jahrhundert: "18XX" (19. Jh. = 18XX, da 19. Jh. = 1800-1899)
- Monat: "1920-03"  Tag: "1920-03-15"
- Undatiert: "" (leerer String)

Antworte IMMER als valides JSON."""


def normalize_edtf_llm(
    date_strings: list[dict[str, str]],
    provider: AIProvider,
    model: str | None = None,
    system_prompt: str = "",
) -> tuple[list[EDTFResult], BatchReport]:
    """
    Convert dates using LLM for complex cases.
    """
    # First pass: rule-based
    results = []
    llm_items = []

    for item in date_strings:
        rule_result = normalize_edtf(item.get("date", ""))
        if rule_result.valid and rule_result.edtf:
            results.append(rule_result)
        elif rule_result.note == "undatiert" or not rule_result.original:
            results.append(rule_result)
        else:
            llm_items.append(item)
            results.append(None)  # placeholder

    if not llm_items:
        return [r for r in results if r is not None], BatchReport()

    # LLM pass for unresolved dates
    def _make_prompt(item: dict) -> list[AIMessage]:
        return [
            AIMessage.system(system_prompt or SYSTEM_EDTF),
            AIMessage.user(
                f'Konvertiere diese Datumsangabe in EDTF:\n\n'
                f'Original: "{item.get("date", "")}"\n'
                f'Record: {item.get("record_id", "")}\n\n'
                f'Antworte als JSON:\n'
                f'{{"original": "...", "edtf": "...", "confidence": 0.0-1.0, "note": "..."}}'
            ),
        ]

    batch = process_batch(provider, llm_items, _make_prompt, model=model)

    # Merge LLM results back
    llm_idx = 0
    final = []
    for r in results:
        if r is not None:
            final.append(r)
        else:
            br = batch.results[llm_idx]
            if br.parsed:
                final.append(EDTFResult(
                    original=br.parsed.get("original", ""),
                    edtf=br.parsed.get("edtf", ""),
                    confidence=float(br.parsed.get("confidence", 0.5)),
                    method="llm",
                    note=br.parsed.get("note", ""),
                    valid=bool(br.parsed.get("edtf")),
                ))
            else:
                final.append(EDTFResult(
                    original=llm_items[llm_idx].get("date", ""),
                    edtf="", confidence=0.0, method="llm",
                    valid=False, note="LLM-Konvertierung fehlgeschlagen",
                ))
            llm_idx += 1

    return final, batch
