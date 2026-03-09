"""
Service-Protokolle für austauschbare Implementierungen.

Definiert runtime-checkable Protocols für die zentralen KI-Dienste,
analog zur AIProvider-Abstraktion in kwb.ai.provider.

Verwendung:
    from kwb.core.interfaces import NerServiceProtocol, DateServiceProtocol

    def run_ner(service: NerServiceProtocol, df, cols):
        return service.run(df, cols)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import pandas as pd

if TYPE_CHECKING:
    from kwb.ai.batch import BatchReport
    from kwb.ai.provider import AIProvider
    from kwb.analyze.ner import NERResult
    from kwb.enrich.edtf import EDTFResult


@runtime_checkable
class NerServiceProtocol(Protocol):
    """
    Schnittstelle für Named-Entity-Recognition-Dienste.

    Konkrete Implementierungen: DefaultNerService (kwb.analyze.ner_service).
    Testdoppel: MockNerService.
    """

    def run(
        self,
        df: pd.DataFrame,
        columns: list[str],
        provider: "AIProvider | None" = None,
        *,
        id_column: str | None = None,
        sample_size: int | None = None,
        model: str | None = None,
        system_prompt: str = "",
        use_spacy: bool = True,
        use_llm: bool = True,
    ) -> "NERResult":
        """Führt NER auf dem DataFrame aus und gibt ein NERResult zurück."""
        ...


@runtime_checkable
class DateServiceProtocol(Protocol):
    """
    Schnittstelle für EDTF-Datumsnormalisierungs-Dienste.

    Konkrete Implementierungen: DefaultDateService (kwb.enrich.date_service).
    Testdoppel: MockDateService.
    """

    def normalize(
        self,
        items: list[dict],
        provider: "AIProvider | None" = None,
        *,
        model: str | None = None,
        system_prompt: str = "",
    ) -> "tuple[list[EDTFResult], BatchReport | None]":
        """Normalisiert Datumsangaben in EDTF-Format."""
        ...
