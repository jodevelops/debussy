"""
EDTF (Extended Date/Time Format) normalization.

Converts free-text date expressions into LOC EDTF (ISO 8601-2) format.
Reference: https://www.loc.gov/standards/datetime/
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Any

from kwb.ai.provider import AIMessage, AIProvider
from kwb.ai.batch import process_batch, BatchReport, _try_parse_json

logger = logging.getLogger(__name__)


@dataclass
class EDTFResult:
    original: str
    edtf: str
    confidence: float = 0.0
    method: str = ""
    note: str = ""
    record_id: str = ""


_MONTHS_DE = {
    "januar":"01","jan":"01","jaenner":"01","februar":"02","feb":"02",
    "maerz":"03","marz":"03","mrz":"03","april":"04","apr":"04","mai":"05",
    "juni":"06","jun":"06","juli":"07","jul":"07","august":"08","aug":"08",
    "september":"09","sep":"09","sept":"09","oktober":"10","okt":"10",
    "november":"11","nov":"11","dezember":"12","dez":"12",
}
_SEASONS_DE = {"fruehling":"21","fruhling":"21","sommer":"22","herbst":"23","winter":"24"}
_UNKNOWN = {"undatiert","o.d.","o.j.","s.d.","ohne datum","n.d.","unbekannt","k.a."}


def normalize_date_rules(text: str) -> EDTFResult | None:
    """Rule-based EDTF. Returns None if no rule matches."""
    orig = text
    t = text.strip().lower()
    t = re.sub(r'\s+', ' ', t)

    if t in _UNKNOWN or not t:
        return EDTFResult(original=orig, edtf="", confidence=1.0, method="rule", note="undatiert")

    # Plain year
    if m := re.fullmatch(r'(\d{4})', t):
        return EDTFResult(original=orig, edtf=m[1], confidence=1.0, method="rule")

    # Full date DD.MM.YYYY
    if m := re.fullmatch(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', t):
        return EDTFResult(original=orig, edtf=f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}", confidence=1.0, method="rule")

    # YYYY-MM-DD
    if m := re.fullmatch(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', t):
        return EDTFResult(original=orig, edtf=f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}", confidence=1.0, method="rule")

    # YYYY-MM
    if m := re.fullmatch(r'(\d{4})[-/.](\d{1,2})', t):
        return EDTFResult(original=orig, edtf=f"{m[1]}-{int(m[2]):02d}", confidence=1.0, method="rule")

    # Approximate
    if m := re.fullmatch(r'(?:um|ca\.?|circa|etwa|approx\.?)\s*(\d{4})', t):
        return EDTFResult(original=orig, edtf=f"{m[1]}~", confidence=0.95, method="rule", note="approximate")

    # Uncertain
    if m := re.fullmatch(r'(\d{4})\s*\?', t):
        return EDTFResult(original=orig, edtf=f"{m[1]}?", confidence=0.95, method="rule", note="uncertain")

    # Range
    if m := re.fullmatch(r'(\d{4})\s*[-\u2013\u2014]\s*(\d{4})', t):
        return EDTFResult(original=orig, edtf=f"{m[1]}/{m[2]}", confidence=1.0, method="rule")
    if m := re.fullmatch(r'(\d{4})\s+bis\s+(\d{4})', t):
        return EDTFResult(original=orig, edtf=f"{m[1]}/{m[2]}", confidence=1.0, method="rule")

    # Decade
    if m := re.fullmatch(r'(\d{3})0(?:er(?:\s+jahre)?|s)', t):
        return EDTFResult(original=orig, edtf=f"{m[1]}X", confidence=0.95, method="rule", note="decade")

    # Century
    if m := re.fullmatch(r'(\d{1,2})\.?\s*(?:jahrhundert|jh\.?|century)', t):
        c = int(m[1])
        return EDTFResult(original=orig, edtf=f"{c-1 if c>0 else c}XX", confidence=0.9, method="rule", note="century")

    # Before / after
    if m := re.fullmatch(r'(?:vor|before)\s+(\d{4})', t):
        return EDTFResult(original=orig, edtf=f"../{m[1]}", confidence=0.9, method="rule", note="before")
    if m := re.fullmatch(r'(?:nach|after|ab)\s+(\d{4})', t):
        return EDTFResult(original=orig, edtf=f"{m[1]}/..", confidence=0.9, method="rule", note="after")

    # Month + year
    for mn, num in _MONTHS_DE.items():
        if m := re.fullmatch(rf'{mn}\s+(\d{{4}})', t):
            return EDTFResult(original=orig, edtf=f"{m[1]}-{num}", confidence=0.95, method="rule")
        if m := re.fullmatch(rf'(\d{{4}})\s+{mn}', t):
            return EDTFResult(original=orig, edtf=f"{m[1]}-{num}", confidence=0.95, method="rule")

    # Season + year
    for sn, code in _SEASONS_DE.items():
        if m := re.fullmatch(rf'{sn}\s+(\d{{4}})', t):
            return EDTFResult(original=orig, edtf=f"{m[1]}-{code}", confidence=0.9, method="rule", note="season")

    return None


SYSTEM_EDTF = """Du bist ein Experte fuer Datumsformate in Archiv- und Bibliotheksdaten.
Normalisiere Datumsangaben in EDTF (Extended Date/Time Format, LOC Standard).

Regeln: 1923, 1923-05, 1923-05-17, 1920~ (ca.), 1920? (unsicher), 1920% (beides),
1920/1930 (Bereich), 192X (Dekade), 19XX (Jh.), ../1900 (vor), 1950/.. (nach),
1923-21..24 (Jahreszeiten). Leer = unbekannt.

Antworte IMMER als valides JSON."""


def normalize_dates_llm(dates, provider, model=None, system_prompt=""):
    def _p(item):
        return [
            AIMessage.system(system_prompt or SYSTEM_EDTF),
            AIMessage.user(f'Normalisiere in EDTF: "{item["text"]}"\n\n'
                          f'JSON: {{"original":"...","edtf":"...","confidence":0.0-1.0,"note":"..."}}'),
        ]
    batch = process_batch(provider, dates, _p, id_field="record_id", model=model)
    results = []
    for r in batch.results:
        if r.parsed:
            results.append(EDTFResult(
                original=r.parsed.get("original", ""), edtf=r.parsed.get("edtf", ""),
                confidence=float(r.parsed.get("confidence", 0.5)),
                method="llm", note=r.parsed.get("note", ""), record_id=r.record_id))
    return results, batch


def normalize_dates(values, provider=None, model=None, system_prompt=""):
    """Hybrid: rules first, LLM for remainder."""
    results, needs_llm = [], []
    for item in values:
        rr = normalize_date_rules(item["text"])
        if rr:
            rr.record_id = item.get("record_id", "")
            results.append(rr)
        else:
            needs_llm.append(item)
    batch = None
    if needs_llm and provider:
        lr, batch = normalize_dates_llm(needs_llm, provider, model=model, system_prompt=system_prompt)
        results.extend(lr)
    return results, batch
