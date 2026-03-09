"""
NerService — konkreter Dienst, der NerServiceProtocol implementiert.

Kapselt ner_hybrid() als Objekt, damit Routen und Tests die Implementierung
via Dependency-Injection austauschen können.

Beispiel (Produktion):
    service = DefaultNerService()
    result = service.run(df, ["Titel", "Beschreibung"])

Beispiel (Test):
    service = MockNerService(entities=[...])
    result = service.run(df, [])
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from kwb.analyze.ner import NERResult, Entity, EntityType, ner_hybrid
from kwb.ai.provider import AIProvider


class DefaultNerService:
    """
    Produktionsimplementierung: SpaCy + LLM-Hybrid.

    Implementiert NerServiceProtocol — kein explizites `implements`,
    da Python Protocols strukturell geprüft werden.
    """

    def run(
        self,
        df: pd.DataFrame,
        columns: list[str],
        provider: AIProvider | None = None,
        *,
        id_column: str | None = None,
        sample_size: int | None = None,
        model: str | None = None,
        system_prompt: str = "",
        use_spacy: bool = True,
        use_llm: bool = True,
    ) -> NERResult:
        return ner_hybrid(
            df,
            columns,
            provider=provider,
            id_column=id_column,
            sample_size=sample_size,
            model=model,
            system_prompt=system_prompt,
            use_spacy=use_spacy,
            use_llm=use_llm,
        )


@dataclass
class MockNerService:
    """
    Testdoppel: gibt vordefinierte Entities zurück, ruft keine KI auf.

    Verwendung in Tests:
        svc = MockNerService(entities=[
            Entity(text="Berlin", entity_type=EntityType.LOC, confidence=0.9),
        ])
        result = svc.run(df, ["Ort"])
        assert len(result.entities) == 1
    """

    entities: list[Entity] = field(default_factory=list)
    call_log: list[dict[str, Any]] = field(default_factory=list)

    def run(
        self,
        df: pd.DataFrame,
        columns: list[str],
        provider: AIProvider | None = None,
        *,
        id_column: str | None = None,
        sample_size: int | None = None,
        model: str | None = None,
        system_prompt: str = "",
        use_spacy: bool = True,
        use_llm: bool = True,
    ) -> NERResult:
        self.call_log.append({
            "rows": len(df),
            "columns": columns,
            "model": model,
            "use_spacy": use_spacy,
            "use_llm": use_llm,
        })
        return NERResult(entities=list(self.entities))
