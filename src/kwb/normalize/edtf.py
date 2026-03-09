"""
EDTF — canonical rule-based date normalization.
This is the master implementation. enrich/edtf.py delegates here.
"""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass, field
from kwb.ai.provider import AIMessage
from kwb.ai.batch import process_batch

logger = logging.getLogger(__name__)

@dataclass
class EDTFResult:
    original: str
    edtf: str
    confidence: float = 1.0
    method: str = "rule"
    note: str = ""
    valid: bool = True
    record_id: str = ""

@dataclass
class EDTFReport:
    results: list = field(default_factory=list)
    total: int = 0
    converted: int = 0
    failed: int = 0
    undated: int = 0

    @property
    def success_rate(self): return self.converted / self.total if self.total > 0 else 0.0

_APPROX = re.compile(r'^(ca\.?|circa|um|ungef[aä]hr|approx\.?|etwa)\s*', re.IGNORECASE)
_BEFORE = re.compile(r'^(vor|before|bis|ante)\s+(\d{4})', re.IGNORECASE)
_AFTER  = re.compile(r'^(nach|after|ab|seit|post)\s+(\d{4})', re.IGNORECASE)
_RANGE  = re.compile(r'^(\d{4})\s*[-\u2013\u2014/]\s*(\d{4})$')
_RANGE_TEXT = re.compile(r'^(\d{4})\s+(bis|to|und|and)\s+(\d{4})$', re.IGNORECASE)
_DECADE = re.compile(r'^(\d{3})0\s*-?(er|er\s+Jahre|s)$', re.IGNORECASE)
_CENTURY= re.compile(r'^(?:Anfang|Mitte|Ende|Beginn)?\s*(\d{1,2})\.\s*(Jh\.?|Jahrhundert|century)', re.IGNORECASE)
_POSITION_CENTURY = re.compile(r'^(Anfang|Beginn|Mitte|Ende|Erstes Drittel|Zweites Drittel|Letztes Drittel)\s+(\d{1,2})\.\s*(Jh\.?|Jahrhundert)', re.IGNORECASE)
_UNCERTAIN_BRACKET = re.compile(r'^\[(\d{4})\]$')
_UNCERTAIN_Q = re.compile(r'^(\d{4})\?$')
_ISO_DAY = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')
_ISO_MONTH = re.compile(r'^(\d{4})-(\d{2})$')
_ISO_YEAR = re.compile(r'^(\d{4})$')
_ISO_DAY_SLASH = re.compile(r'^(\d{4})[/.](\d{2})[/.](\d{2})$')   # 1920/03/15 or 1920.03.15
_FULL_DATE_DE = re.compile(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$')
_UNDATED = re.compile(r'^(o\.?\s*[dDjJ]\.?|undatiert|undated|s\.?\s*d\.?|ohne Datum|keine Angabe|n\.?\s*d\.?|unbekannt|k\.a\.)$', re.IGNORECASE)

_MONTHS_DE = {
    "januar":"01", "jan":"01", "jaenner":"01", "jänner":"01",
    "februar":"02", "feb":"02",
    "maerz":"03", "marz":"03", "märz":"03", "mrz":"03",
    "april":"04", "apr":"04",
    "mai":"05",
    "juni":"06", "jun":"06",
    "juli":"07", "jul":"07",
    "august":"08", "aug":"08",
    "september":"09", "sep":"09", "sept":"09",
    "oktober":"10", "okt":"10",
    "november":"11", "nov":"11",
    "dezember":"12", "dez":"12",
}
_SEASONS_DE = {
    "frühling":"21", "fruehling":"21", "fruhling":"21",
    "sommer":"22",
    "herbst":"23",
    "winter":"24",
}

SYSTEM_EDTF = """Du bist ein Experte fuer Datumsformate in Archiv- und Bibliotheksdaten.
Normalisiere Datumsangaben in EDTF (Extended Date/Time Format, LOC Standard).

Regeln: 1923, 1923-05, 1923-05-17, 1920~ (ca.), 1920? (unsicher),
1920/1930 (Bereich), 192X (Dekade), 19XX (Jh.), ../1900 (vor), 1950/.. (nach).
Leer = unbekannt. Antworte IMMER als valides JSON."""


def normalize_edtf(date_str: str) -> EDTFResult:
    """Rule-based EDTF conversion. Returns EDTFResult (valid=False if no match)."""
    original = date_str.strip()
    if not original:
        return EDTFResult(original="", edtf="", confidence=1.0, note="leer")

    text = original.strip()

    if _UNDATED.match(text):
        return EDTFResult(original=original, edtf="", confidence=1.0, note="undatiert")

    approx = False
    m = _APPROX.match(text)
    if m:
        approx = True; text = text[m.end():].strip()

    q = "~" if approx else ""
    approx_note = "approximate" if approx else ""

    if m := _UNCERTAIN_BRACKET.match(text):
        return EDTFResult(original=original, edtf=f"{m[1]}?", confidence=0.95, note="unsicher (Klammern)")
    if m := _UNCERTAIN_Q.match(text):
        return EDTFResult(original=original, edtf=f"{m[1]}?", confidence=0.95, note="unsicher")
    if m := _BEFORE.match(text):
        return EDTFResult(original=original, edtf=f"../{m[2]}{q}", confidence=0.9, note=f"vor {m[2]}")
    if m := _AFTER.match(text):
        return EDTFResult(original=original, edtf=f"{m[2]}{q}/..", confidence=0.9, note=f"nach {m[2]}")
    if m := _RANGE.match(text) or _RANGE_TEXT.match(text):
        g = m.groups(); y1, y2 = g[0], g[-1]
        return EDTFResult(original=original, edtf=f"{y1}{q}/{y2}{q}", confidence=0.95, note=f"{y1}–{y2}")
    if m := _DECADE.match(text):
        return EDTFResult(original=original, edtf=f"{m[1]}X{q}", confidence=0.9, note=f"{m[1]}0er")
    if m := _POSITION_CENTURY.match(text):
        c = int(m[2]) - 1
        return EDTFResult(original=original, edtf=f"{c:02d}XX{q}", confidence=0.7, note=f"{m[1]} {m[2]}. Jh.")
    if m := _CENTURY.match(text):
        c = int(m[1]) - 1
        return EDTFResult(original=original, edtf=f"{c:02d}XX{q}", confidence=0.85, note=f"{m[1]}. Jh.")
    if m := _FULL_DATE_DE.match(text):
        return EDTFResult(original=original, edtf=f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}{q}", confidence=1.0)
    if m := _ISO_DAY_SLASH.match(text):
        return EDTFResult(original=original, edtf=f"{m[1]}-{m[2]}-{m[3]}{q}", confidence=1.0)
    if m := _ISO_DAY.match(text):
        return EDTFResult(original=original, edtf=f"{text}{q}", confidence=1.0, note=approx_note)
    if m := _ISO_MONTH.match(text):
        return EDTFResult(original=original, edtf=f"{text}{q}", confidence=1.0, note=approx_note)
    if m := _ISO_YEAR.match(text):
        return EDTFResult(original=original, edtf=f"{text}{q}", confidence=1.0, note=approx_note)

    # Month name + year
    for mn, num in _MONTHS_DE.items():
        if mm := re.fullmatch(rf'{re.escape(mn)}\s+(\d{{4}})', text, re.IGNORECASE):
            return EDTFResult(original=original, edtf=f"{mm[1]}-{num}{q}", confidence=0.95)
        if mm := re.fullmatch(rf'(\d{{4}})\s+{re.escape(mn)}', text, re.IGNORECASE):
            return EDTFResult(original=original, edtf=f"{mm[1]}-{num}{q}", confidence=0.95)

    # Season
    for sn, code in _SEASONS_DE.items():
        if mm := re.fullmatch(rf'{re.escape(sn)}\s+(\d{{4}})', text, re.IGNORECASE):
            return EDTFResult(original=original, edtf=f"{mm[1]}-{code}{q}", confidence=0.9, note="season")
        if mm := re.fullmatch(rf'(\d{{4}})\s+{re.escape(sn)}', text, re.IGNORECASE):
            return EDTFResult(original=original, edtf=f"{mm[1]}-{code}{q}", confidence=0.9, note="season")

    return EDTFResult(original=original, edtf="", confidence=0.0, method="rule",
                      valid=False, note="Kein Muster erkannt — LLM-Fallback empfohlen")


def normalize_edtf_batch(date_strings: list[dict]) -> EDTFReport:
    """
    Batch EDTF normalization (rules only).

    Input items: list of dicts with keys:
        - "text" (required): raw date string
        - "record_id" (optional): identifier attached to the result
    """
    report = EDTFReport(total=len(date_strings))
    for item in date_strings:
        text = item.get("text", item.get("date", ""))
        rid = item.get("record_id", "")
        r = normalize_edtf(text)
        r.record_id = rid
        report.results.append(r)
        if not r.original or r.note == "undatiert":
            report.undated += 1
        elif r.valid and r.edtf:
            report.converted += 1
        else:
            report.failed += 1
    return report


def normalize_edtf_llm(date_strings, provider, model=None, system_prompt=""):
    """
    Hybrid EDTF normalization: rules first, LLM fallback for unmatched items.

    When provider is None, unmatched dates return a result with valid=False.
    Returns (list[EDTFResult], BatchReport | None).
    """
    results: list[EDTFResult | None] = []
    llm_items: list[dict] = []

    for item in date_strings:
        text = item.get("text", item.get("date", ""))
        rid = item.get("record_id", "")
        r = normalize_edtf(text)
        r.record_id = rid
        if (r.valid and r.edtf) or r.note == "undatiert" or not r.original:
            results.append(r)
        else:
            llm_items.append(item)
            results.append(None)

    if not llm_items or provider is None:
        # Fill None slots with failed results
        final: list[EDTFResult] = []
        llm_idx = 0
        for r in results:
            if r is not None:
                final.append(r)
            else:
                item = llm_items[llm_idx]
                text = item.get("text", item.get("date", ""))
                rid = item.get("record_id", "")
                final.append(EDTFResult(
                    original=text, edtf="", confidence=0.0,
                    method="rule", valid=False,
                    note="Kein Muster erkannt — kein LLM-Provider verfügbar",
                    record_id=rid,
                ))
                llm_idx += 1
        return final, None

    def _p(item):
        text = item.get("text", item.get("date", ""))
        rid = item.get("record_id", "")
        return [
            AIMessage.system(system_prompt or SYSTEM_EDTF),
            AIMessage.user(
                f'Konvertiere in EDTF: "{text}" Record: {rid}\n\n'
                f'JSON: {{"original":"...","edtf":"...","confidence":0.0-1.0,"note":"..."}}'
            ),
        ]

    batch = process_batch(provider, llm_items, _p, model=model)
    llm_idx = 0
    final = []
    for r in results:
        if r is not None:
            final.append(r)
        else:
            br = batch.results[llm_idx]
            item = llm_items[llm_idx]
            rid = item.get("record_id", "")
            if br.parsed:
                final.append(EDTFResult(
                    original=br.parsed.get("original", ""),
                    edtf=br.parsed.get("edtf", ""),
                    confidence=float(br.parsed.get("confidence", 0.5)),
                    method="llm",
                    note=br.parsed.get("note", ""),
                    valid=bool(br.parsed.get("edtf")),
                    record_id=rid,
                ))
            else:
                text = item.get("text", item.get("date", ""))
                final.append(EDTFResult(
                    original=text, edtf="", confidence=0.0,
                    method="llm", valid=False, record_id=rid,
                ))
            llm_idx += 1
    return final, batch
# Alias for test compatibility
normalize_edtf_hybrid = normalize_edtf_llm
