"""
EDTF (Extended Date/Time Format) normalization — enrich module entry point.

Delegates to kwb.normalize.edtf for all rule-based logic (the canonical
implementation). This module adds the LLM-hybrid layer on top and provides
the public API used by app.py.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from kwb.normalize.edtf import (
    normalize_edtf as _normalize_edtf,
    SYSTEM_EDTF,
)
from kwb.ai.provider import AIMessage, AIProvider
from kwb.ai.batch import process_batch, BatchReport

logger = logging.getLogger(__name__)


@dataclass
class EDTFResult:
    """Public EDTFResult used by app.py and workspace."""
    original: str
    edtf: str
    confidence: float = 0.0
    method: str = ""
    note: str = ""
    record_id: str = ""


def normalize_date_rules(text: str) -> EDTFResult | None:
    """Rule-based EDTF conversion. Returns None if no rule matched."""
    r = _normalize_edtf(text)
    if not r.valid and r.confidence == 0.0:
        return None
    return EDTFResult(
        original=r.original, edtf=r.edtf,
        confidence=r.confidence, method=r.method, note=r.note,
    )


def _normalize_dates_llm(
    items: list[dict],
    provider: AIProvider,
    model: str | None = None,
    system_prompt: str = "",
) -> tuple[list[EDTFResult], BatchReport]:
    from kwb.ai.prompts import resolve_system_prompt
    resolved_prompt, prompt_fp = resolve_system_prompt(
        system_prompt, SYSTEM_EDTF, task="edtf",
    )

    def _p(item):
        return [
            AIMessage.system(resolved_prompt),
            AIMessage.user(
                f'Normalisiere in EDTF: "{item["text"]}"\n\n'
                f'JSON: {{"original":"...","edtf":"...","confidence":0.0-1.0,"note":"..."}}'
            ),
        ]
    batch = process_batch(provider, items, _p, id_field="record_id", model=model)
    batch.system_prompt_used = prompt_fp

    # Pre-build lookup dict for O(1) access instead of O(n²) search
    items_by_id = {item.get("record_id"): item for item in items}

    results = []
    for r in batch.results:
        if r.parsed:
            results.append(EDTFResult(
                original=r.parsed.get("original", ""),
                edtf=r.parsed.get("edtf", ""),
                confidence=float(r.parsed.get("confidence", 0.5)),
                method="llm",
                note=r.parsed.get("note", ""),
                record_id=r.record_id,
            ))
        else:
            # LLM failed — emit empty result with original text for retry/logging
            item = items_by_id.get(r.record_id, {})
            results.append(EDTFResult(
                original=item.get("text", ""),
                edtf="",
                confidence=0.0,
                method="llm",
                note="LLM-Konvertierung fehlgeschlagen",
                record_id=r.record_id,
            ))
    return results, batch


def normalize_dates(
    values: list[dict],
    provider: AIProvider | None = None,
    model: str | None = None,
    system_prompt: str = "",
) -> tuple[list[EDTFResult], BatchReport | None]:
    """
    Hybrid EDTF: rules first, LLM for remainder.

    Args:
        values: [{"record_id": "...", "text": "..."}]
        provider: Optional AI provider for LLM fallback.
        model: Model name override.
        system_prompt: Override system prompt.

    Returns:
        (results, batch_report_or_None)
    """
    results: list[EDTFResult] = []
    needs_llm: list[dict] = []

    for item in values:
        norm = _normalize_edtf(item["text"])
        if norm.valid or norm.note in ("undatiert", "leer"):
            results.append(EDTFResult(
                original=norm.original, edtf=norm.edtf,
                confidence=norm.confidence, method=norm.method,
                note=norm.note, record_id=item.get("record_id", ""),
            ))
        else:
            needs_llm.append(item)

    batch: BatchReport | None = None
    if needs_llm and provider:
        llm_results, batch = _normalize_dates_llm(
            needs_llm, provider, model=model, system_prompt=system_prompt
        )
        results.extend(llm_results)

    # For items that needed LLM but no provider available, add unresolved entries
    if needs_llm and not provider:
        for item in needs_llm:
            results.append(EDTFResult(
                original=item["text"], edtf="",
                confidence=0.0, method="rule",
                note="Kein Muster erkannt — LLM deaktiviert",
                record_id=item.get("record_id", ""),
            ))

    return results, batch
