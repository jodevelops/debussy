"""
DateService — konkreter Dienst, der DateServiceProtocol implementiert.

Kapselt normalize_dates() als Objekt, damit Routen und Tests die
Implementierung via Dependency-Injection austauschen können.

Beispiel (Produktion):
    service = DefaultDateService()
    results, report = service.normalize([{"text": "1. Januar 1920", "record_id": "001"}])

Beispiel (Test):
    service = MockDateService(results=[EDTFResult(original="1920", edtf="1920")])
    results, _ = service.normalize([{"text": "1920", "record_id": "001"}])
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kwb.ai.batch import BatchReport
from kwb.ai.provider import AIProvider
from kwb.enrich.edtf import EDTFResult, normalize_dates


class DefaultDateService:
    """
    Produktionsimplementierung: Regelbasiert + LLM-Fallback.

    Implementiert DateServiceProtocol — kein explizites `implements`,
    da Python Protocols strukturell geprüft werden.
    """

    def normalize(
        self,
        items: list[dict],
        provider: AIProvider | None = None,
        *,
        model: str | None = None,
        system_prompt: str = "",
    ) -> tuple[list[EDTFResult], BatchReport | None]:
        return normalize_dates(
            items,
            provider=provider,
            model=model,
            system_prompt=system_prompt,
        )


@dataclass
class MockDateService:
    """
    Testdoppel: gibt vordefinierte EDTFResults zurück, ruft keine KI auf.

    Verwendung in Tests:
        svc = MockDateService(results=[
            EDTFResult(original="um 1920", edtf="1920~", confidence=0.8, method="mock"),
        ])
        results, report = svc.normalize([{"text": "um 1920", "record_id": "001"}])
        assert results[0].edtf == "1920~"
    """

    results: list[EDTFResult] = field(default_factory=list)
    call_log: list[dict[str, Any]] = field(default_factory=list)

    def normalize(
        self,
        items: list[dict],
        provider: AIProvider | None = None,
        *,
        model: str | None = None,
        system_prompt: str = "",
    ) -> tuple[list[EDTFResult], None]:
        self.call_log.append({
            "item_count": len(items),
            "model": model,
            "has_provider": provider is not None,
        })
        return list(self.results), None
